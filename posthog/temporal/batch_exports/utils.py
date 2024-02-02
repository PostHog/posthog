import collections.abc
import typing

T = typing.TypeVar("T")


def peek_first_and_rewind(
    gen: collections.abc.Generator[T, None, None]
) -> tuple[T, collections.abc.Generator[T, None, None]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    first = next(gen)

    def rewind_gen() -> collections.abc.Generator[T, None, None]:
        """Yield the item we popped to rewind the generator."""
        yield first
        for i in gen:
            yield i

    return (first, rewind_gen())
