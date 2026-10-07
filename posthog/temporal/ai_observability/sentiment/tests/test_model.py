import threading
from concurrent.futures import ThreadPoolExecutor

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai_observability.sentiment import model
from posthog.temporal.ai_observability.sentiment.model import classify
from posthog.temporal.ai_observability.sentiment.schema import SentimentResult


def _make_pipeline_output(label: str, score: float) -> list[dict[str, object]]:
    """Build a single pipeline result (list of label/score dicts)."""
    labels_scores = {
        "positive": 0.05,
        "neutral": 0.05,
        "negative": 0.05,
    }
    labels_scores[label] = score
    return [{"label": name, "score": s} for name, s in labels_scores.items()]


class _SignallingLock:
    """Wraps a real lock and signals when a second thread tries to take it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts = 0
        self._attempts_lock = threading.Lock()
        self.second_acquire_attempted = threading.Event()

    def __enter__(self) -> "_SignallingLock":
        with self._attempts_lock:
            self._attempts += 1
            if self._attempts == 2:
                self.second_acquire_attempted.set()
        assert self._lock.acquire(timeout=5)
        return self

    def __exit__(self, *args: object) -> None:
        self._lock.release()


class TestClassifyBatch:
    @parameterized.expand(
        [
            ("empty_input", [], []),
            (
                "single_text",
                ["hello"],
                [
                    SentimentResult(
                        label="positive", score=0.9, scores={"positive": 0.9, "neutral": 0.05, "negative": 0.05}
                    )
                ],
            ),
            (
                "multiple_texts",
                ["great", "terrible"],
                [
                    SentimentResult(
                        label="positive", score=0.9, scores={"positive": 0.9, "neutral": 0.05, "negative": 0.05}
                    ),
                    SentimentResult(
                        label="negative", score=0.8, scores={"positive": 0.05, "neutral": 0.05, "negative": 0.8}
                    ),
                ],
            ),
        ]
    )
    @patch("posthog.temporal.ai_observability.sentiment.model._load_pipeline")
    def test_classify(self, _name: str, texts: list[str], expected: list[SentimentResult], mock_load: MagicMock):
        if not texts:
            result = classify(texts)
            assert result == expected
            mock_load.assert_not_called()
            return

        mock_pipe = MagicMock()
        labels = ["positive", "negative", "neutral", "positive"]
        pipeline_outputs = []
        for i, _text in enumerate(texts):
            label = labels[i % len(labels)]
            score = 0.9 if label == "positive" else 0.8
            pipeline_outputs.append(_make_pipeline_output(label, score))

        mock_pipe.return_value = pipeline_outputs
        mock_load.return_value = mock_pipe

        result = classify(texts)

        mock_pipe.assert_called_once_with(texts, batch_size=32)
        assert len(result) == len(expected)
        for r, e in zip(result, expected):
            assert r.label == e.label
            assert r.score == e.score

    @patch("posthog.temporal.ai_observability.sentiment.model._load_pipeline")
    def test_low_confidence_polar_score_resolves_to_neutral(self, mock_load: MagicMock):
        # A near-tie that argmaxes to negative must come back neutral — guards the wiring
        # of the neutral-margin gate into the model's result parsing.
        mock_pipe = MagicMock()
        mock_pipe.return_value = [
            [
                {"label": "negative", "score": 0.504},
                {"label": "neutral", "score": 0.468},
                {"label": "positive", "score": 0.028},
            ]
        ]
        mock_load.return_value = mock_pipe

        result = classify(["retention graph for these people"])

        assert result[0].label == "neutral"

    @patch("posthog.temporal.ai_observability.sentiment.model._load_pipeline")
    def test_missing_labels_filled_with_zero(self, mock_load: MagicMock):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [[{"label": "positive", "score": 0.95}]]
        mock_load.return_value = mock_pipe

        result = classify(["text"])

        assert result[0].scores["neutral"] == 0.0
        assert result[0].scores["negative"] == 0.0
        assert result[0].scores["positive"] == 0.95

    @patch("posthog.temporal.ai_observability.sentiment.model._load_pipeline")
    def test_concurrent_calls_never_run_pipeline_in_parallel(self, mock_load: MagicMock):
        first_call_entered = threading.Event()
        release_first_call = threading.Event()
        signalling_lock = _SignallingLock()
        pipe_calls = 0

        def fake_pipe(texts: list[str], batch_size: int) -> list[list[dict[str, object]]]:
            nonlocal pipe_calls
            pipe_calls += 1
            if pipe_calls == 1:
                first_call_entered.set()
                assert release_first_call.wait(timeout=5)
            return [_make_pipeline_output("positive", 0.9) for _ in texts]

        mock_load.return_value = fake_pipe

        with (
            patch.object(model, "_inference_lock", signalling_lock),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(classify, ["first"])
            assert first_call_entered.wait(timeout=5)
            second = executor.submit(classify, ["second"])
            assert signalling_lock.second_acquire_attempted.wait(timeout=5)
            assert pipe_calls == 1
            release_first_call.set()
            results = [first.result(timeout=5), second.result(timeout=5)]

        assert pipe_calls == 2
        assert all(r[0].label == "positive" for r in results)
