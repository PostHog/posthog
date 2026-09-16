from typing import Any

from celery.utils.log import get_logger
from redbeat import RedBeatScheduler
from redbeat.schedulers import LUA_EXTEND_TO_SCRIPT, get_redis

logger = get_logger("celery.beat")


class ResilientRedBeatScheduler(RedBeatScheduler):
    """RedBeatScheduler that survives a failed startup lock acquisition.

    celery-redbeat wires ``acquire_distributed_beat_lock`` to the ``beat_init`` signal, where it
    calls ``lock.acquire()``. Celery swallows any exception raised in a signal handler, so a
    transient Redis blip at startup leaves ``self.lock`` as ``None`` while ``self.lock_key`` stays
    set — a race redbeat's own docstring calls out. Stock ``tick()`` then runs
    ``self.lock.extend(...)`` unconditionally and dies with
    ``AttributeError: 'NoneType' object has no attribute 'extend'``, taking down the single beat
    process that schedules every periodic task.

    Guard the tick: if the lock is missing, try to acquire it before extending, and if that fails
    (Redis still unhealthy) skip the tick instead of crashing so beat recovers on a later tick.
    """

    def _acquire_lock(self) -> None:
        redis_client = get_redis(self.app)
        lock = redis_client.lock(
            self.lock_key,
            timeout=self.lock_timeout,
            sleep=self.max_interval,
        )
        # Mirror upstream: overwrite redis-py's extend script so extend sets an absolute
        # timeout instead of adding to the remaining one.
        lock.lua_extend = redis_client.register_script(LUA_EXTEND_TO_SCRIPT)
        lock.acquire()
        self.lock = lock

    def tick(self, **kwargs: Any) -> float:
        if self.lock_key and self.lock is None:
            logger.warning("beat: lock missing at tick (startup lock acquisition failed); re-acquiring")
            try:
                self._acquire_lock()
            except Exception:
                logger.warning("beat: failed to re-acquire lock, skipping tick", exc_info=True)
                return self.max_interval
            logger.info("beat: Re-acquired lock")
        return super().tick(**kwargs)
