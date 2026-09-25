"""
Static int8 quantization of a detector, calibrated on inputs dumped by dev/text-det-bench.ts or
dev/face-bench.ts.

    tsx dev/text-det-bench.ts --dump-calibration "ppocrv3 (prod)"
    uv run --with onnxruntime --with onnx python dev/text-det-quantize.py \
        models/dbnet_det.onnx out/text-det-calibration/ppocrv3_prod_ models/candidates/ppocrv3_det_int8.onnx

The PP-OCRv3 export keeps its weights in Constant nodes, which the quantizer does not treat as weights
and ORT's optimizer does not turn into initializers, so they are moved to initializers first. ORT's
basic optimizations then fold batch norm into the convolutions, which quant_pre_process leaves in place,
and an unfused batch norm between a convolution and its output quantizer keeps ORT from running that
convolution in int8.
"""

import sys
import json
import argparse
import tempfile
from pathlib import Path

import onnx
import numpy as np
import onnxruntime as ort
from onnxruntime.quantization import CalibrationDataReader, CalibrationMethod, QuantFormat, QuantType, quantize_static


class DumpedInputs(CalibrationDataReader):
    def __init__(self, directory: Path, input_name: str) -> None:
        index = json.loads((directory / "index.json").read_text())
        self.tensors = iter(
            np.fromfile(directory / entry["file"], dtype=np.float32).reshape(entry["shape"]) for entry in index
        )
        self.input_name = input_name

    def get_next(self) -> dict[str, np.ndarray] | None:
        tensor = next(self.tensors, None)
        return None if tensor is None else {self.input_name: tensor}


def constants_to_initializers(model: onnx.ModelProto) -> onnx.ModelProto:
    graph = model.graph
    kept = []
    for node in graph.node:
        value = next((a.t for a in node.attribute if a.name == "value" and a.HasField("t")), None)
        if node.op_type == "Constant" and value is not None:
            value.name = node.output[0]
            graph.initializer.append(value)
        else:
            kept.append(node)
    del graph.node[:]
    graph.node.extend(kept)
    return model


def at_least_opset_13(model: onnx.ModelProto) -> onnx.ModelProto:
    # Per-channel weights need DequantizeLinear's axis attribute, which only exists from opset 13.
    default = next((o.version for o in model.opset_import if o.domain in ("", "ai.onnx")), 13)
    return onnx.version_converter.convert_version(model, 13) if default < 13 else model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("calibration_dir", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--conv-only", action="store_true", help="quantize only the Conv nodes")
    args = parser.parse_args()
    source, calibration_dir, destination = args.source, args.calibration_dir, args.destination
    with tempfile.TemporaryDirectory() as scratch:
        lifted = Path(scratch) / "lifted.onnx"
        onnx.save(at_least_opset_13(constants_to_initializers(onnx.load(str(source)))), str(lifted))
        folded = Path(scratch) / "folded.onnx"
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.optimized_model_filepath = str(folded)
        ort.InferenceSession(str(lifted), options, providers=["CPUExecutionProvider"])
        input_name = onnx.load(str(folded)).graph.input[0].name
        quantize_static(
            str(folded),
            str(destination),
            DumpedInputs(calibration_dir, input_name),
            quant_format=QuantFormat.QDQ,
            per_channel=True,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
            calibrate_method=CalibrationMethod.MinMax,
            op_types_to_quantize=["Conv"] if args.conv_only else None,
        )
    sys.stdout.write(f"wrote {destination}\n")


if __name__ == "__main__":
    main()
