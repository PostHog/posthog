import uuid
from collections import OrderedDict
from functools import partial
from threading import Condition, Thread
from time import perf_counter
from typing import Callable, Dict, Optional, Tuple

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


class TimerTask:
    id: str
    done: bool

    def __init__(self, callback: Callable, *args, **kwargs):
        self.callback = partial(callback, *args, **kwargs)
        self.id = str(uuid.uuid4())
        self.done = False

    def run(self):
        self.done = True
        try:
            self.callback()
        except Exception as err:
            logger.warn("TimerTask failed, ignoring error", err)


class SingleThreadedTimer(Thread):
    def __init__(self, timeout_ms: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDaemon(True)

        self.timeout_ms = timeout_ms
        self.started = False
        self.lock = Condition()
        self.tasks: OrderedDict = OrderedDict()

    def schedule(self, callback: Callable, *args, **kwargs) -> TimerTask:
        """
        Schedules a task to be called in `timeout_ms`. Returns a TimerTask instance,
        which can be cancelled via `.cancel`

        First call to this starts a background daemon thread.
        """
        self.start()

        with self.lock:
            task = TimerTask(callback, *args, **kwargs)
            self.tasks[task.id] = (task, perf_counter())
            self.lock.notify()

            return task

    def cancel(self, task: TimerTask) -> None:
        with self.lock:
            try:
                del self.tasks[task.id]
            except:
                pass
            self.lock.notify()

    # :TRICKY: We override start() to make it easy to start the thread when scheduling the first task
    def start(self):
        if not self.started:
            self.started = True
            super().start()

    def run(self):
        while True:
            job = None
            with self.lock:
                sleep = self._sleep_time_until_next_task()
                if len(self.tasks) == 0:
                    # Wait until a task is scheduled
                    self.lock.wait()
                elif sleep > 0:
                    self.lock.wait(sleep)
                else:
                    _, (job, _) = self.tasks.popitem(last=False)

            if job is not None:
                job.run()

    def _next_task(self) -> Optional[Tuple[TimerTask, float]]:
        for _, task_and_time in self.tasks.items():
            return task_and_time
        return None

    def _sleep_time_until_next_task(self) -> float:
        "Return time until the next task should be executed, if any task is scheduled"
        next_task = self._next_task()
        if next_task is None:
            return 0
        else:
            _, start_time = next_task
            return start_time + self.timeout_ms / 1000.0 - perf_counter()


class TestSingleThreadedTimer(SingleThreadedTimer):
    def run(self):
        pass


_threads: Dict[str, SingleThreadedTimer] = {}


def get_timer_thread(name: str, timeout_ms: int) -> SingleThreadedTimer:
    if settings.TEST:
        return TestSingleThreadedTimer(timeout_ms=timeout_ms)

    if name not in _threads:
        _threads[name] = SingleThreadedTimer(timeout_ms=timeout_ms)

    return _threads[name]
