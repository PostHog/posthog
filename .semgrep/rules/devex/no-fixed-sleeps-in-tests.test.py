import time
import asyncio
import time as clock
from time import sleep as pause
from asyncio import sleep as async_sleep


def test_waits():
    # ruleid: no-fixed-sleeps-in-tests
    time.sleep(1)
    # ruleid: no-fixed-sleeps-in-tests
    clock.sleep(1)
    # ruleid: no-fixed-sleeps-in-tests
    pause(1)
    # ruleid: no-fixed-sleeps-in-tests
    time.sleep(1)  # noqa: TID251


def test_clock_reference():
    # ok: no-fixed-sleeps-in-tests
    return time.sleep


async def test_async_waits():
    # ruleid: no-fixed-sleeps-in-tests
    await asyncio.sleep(0.1)
    # ruleid: no-fixed-sleeps-in-tests
    await async_sleep(delay)


async def test_cooperative_yield():
    # ok: no-fixed-sleeps-in-tests
    await async_sleep(0)


def test_elapsed_time_is_the_behavior():
    # ok: no-fixed-sleeps-in-tests
    time.sleep(1)  # nosemgrep: no-fixed-sleeps-in-tests -- exercises a real elapsed-time deadline
