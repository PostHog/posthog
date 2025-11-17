import typing
import asyncio
import collections.abc


async def get_record_batch_from_queue(queue, produce_task):
    while not queue.empty() or not produce_task.done():
        try:
            record_batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            if produce_task.done():
                break
            else:
                await asyncio.sleep(0)
                continue

        return record_batch
    return None


def remove_duplicates_from_records(
    records: list[dict[str, typing.Any]], key: collections.abc.Sequence[str] | None = None
) -> list[dict[str, typing.Any]]:
    """Remove duplicates from a list of records.

    Used in batch exports testing when we expect a number of duplicates not known
    beforehand to be present in the results. Since we can't know how many duplicates
    there are, and which exact records will be duplicated, we remove them so that
    comparisons won't fail.
    """
    if not key:
        dedup_key: tuple[str, ...] = ("uuid",)
    else:
        dedup_key = tuple(key)

    seen = set()

    def is_record_seen(record: dict[str, typing.Any]) -> bool:
        nonlocal seen

        pk = tuple(record[k] for k in dedup_key)

        if pk in seen:
            return True

        seen.add(pk)
        return False

    inserted_records = [record for record in records if not is_record_seen(record)]

    return inserted_records
