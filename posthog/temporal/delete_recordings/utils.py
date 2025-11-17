from itertools import islice


def batched(iterable, batch_size: int):
    # batched('ABCDEFG', 2) → AB CD EF G

    # https://docs.python.org/3/library/itertools.html#itertools.batched

    if batch_size < 1:
        raise ValueError("batch_size must be at least one")

    iterator = iter(iterable)

    while batch := tuple(islice(iterator, batch_size)):
        yield batch
