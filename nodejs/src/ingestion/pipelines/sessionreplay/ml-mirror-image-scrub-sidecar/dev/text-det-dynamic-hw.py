"""
Makes a docTR detector's input height and width dynamic, so dev/text-det-bench.ts can run it on the
canvas the scale plan chooses instead of the 1024x1024 it was exported with.

    uv run --with onnxruntime --with onnx python dev/text-det-dynamic-hw.py \
        models/candidates/doctr_fast_tiny.onnx models/candidates/doctr_fast_tiny_dyn.onnx

The networks are fully convolutional and size their upsampling from the input's shape, so only the
declared shapes pin them. Clearing those is enough, which the check at the end confirms.
"""

import sys

import onnx
import numpy as np
import onnxruntime as ort


def main() -> None:
    source, destination = sys.argv[1:3]
    model = onnx.load(source)
    graph = model.graph
    dims = graph.input[0].type.tensor_type.shape.dim
    for dim, name in zip(dims, ["batch", None, "height", "width"]):
        if name:
            dim.ClearField("dim_value")
            dim.dim_param = name
    for output in graph.output:
        for dim in output.type.tensor_type.shape.dim[2:]:
            dim.ClearField("dim_value")
            dim.dim_param = ""
    del graph.value_info[:]
    onnx.save(model, destination)

    session = ort.InferenceSession(destination, providers=["CPUExecutionProvider"])
    for height, width in [(416, 736), (288, 512)]:
        tensor = np.zeros((1, 3, height, width), dtype=np.float32)
        shape = session.run(None, {session.get_inputs()[0].name: tensor})[0].shape
        if shape[2:] != (height, width):
            raise SystemExit(f"{destination}: {height}x{width} input gave {shape}")
    sys.stdout.write(f"wrote {destination}\n")


if __name__ == "__main__":
    main()
