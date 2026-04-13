from collections.abc import AsyncGenerator, Callable, Iterator
from typing import Any, Optional


class Resource:
    """Lightweight resource wrapper that replaces DltResource.

    Supports the interface consumed by the pipeline:
    - ``name``: resource name
    - ``_hints``: dict with ``primary_key``, ``columns``, ``write_disposition``, etc.
    - ``add_map(fn)``: add per-item transformation
    - ``add_filter(fn)``: add per-item filter
    - iteration: yields pages of data (list[dict])
    """

    def __init__(
        self,
        generator_fn: Callable[..., AsyncGenerator[Any, Any]],
        *,
        name: str,
        hints: dict[str, Any],
        args: tuple[Any, ...] = (),
        kwargs: Optional[dict[str, Any]] = None,
        data_from: Optional["Resource"] = None,
    ) -> None:
        self.name = name
        self._hints = hints
        self._maps: list[Callable[[dict[str, Any]], dict[str, Any]]] = []
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._generator_fn = generator_fn
        self._args = args
        self._kwargs = kwargs or {}
        self._data_from = data_from

    def add_map(self, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> "Resource":
        self._maps.append(fn)
        return self

    def add_filter(self, fn: Callable[[dict[str, Any]], bool]) -> "Resource":
        self._filters.append(fn)
        return self

    def _apply_transforms(self, page: Any) -> list[dict[str, Any]]:
        if not isinstance(page, list):
            items = list(page) if hasattr(page, "__iter__") else [page]
        else:
            items = page

        result = []
        for item in items:
            if not isinstance(item, dict):
                result.append(item)
                continue
            skip = False
            for f in self._filters:
                if not f(item):
                    skip = True
                    break
            if skip:
                continue
            for m in self._maps:
                item = m(item)
            result.append(item)
        return result

    def __iter__(self) -> Iterator[Any]:
        import asyncio

        gen = self._generator_fn(*self._args, **self._kwargs)

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot iterate Resource synchronously from within a running event loop. Use async iteration instead."
            )

        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    page = loop.run_until_complete(gen.__anext__())
                    transformed = self._apply_transforms(page)
                    if transformed:
                        yield transformed
                except StopAsyncIteration:
                    break
        finally:
            loop.close()
