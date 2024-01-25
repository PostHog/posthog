import collections.abc
import typing

T = typing.TypeVar("T")


async def peek_first_and_rewind(
    gen: collections.abc.AsyncGenerator[T, None]
) -> tuple[T, collections.abc.AsyncGenerator[T, None]]:
    """Peek into the first element in a generator and rewind the advance.

    The generator is advanced and cannot be reversed, so we create a new one that first
    yields the element we popped before yielding the rest of the generator.

    Returns:
        A tuple with the first element of the generator and the generator itself.
    """
    first = await anext(gen)

    async def rewind_gen() -> collections.abc.AsyncGenerator[T, None]:
        """Yield the item we popped to rewind the generator."""
        yield first
        async for i in gen:
            yield i

    return (first, rewind_gen())
