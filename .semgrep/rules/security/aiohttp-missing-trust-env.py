# Test cases for aiohttp-missing-trust-env rule
# ruff: noqa: F841, E501 — assignments exist solely to give semgrep something to match

import aiohttp
from aiohttp import ClientSession

# ============================================================
# Should flag: ClientSession without trust_env
# ============================================================


async def test_no_trust_env():
    # ruleid: aiohttp-missing-trust-env
    async with aiohttp.ClientSession() as session:
        pass


async def test_no_trust_env_with_other_kwargs():
    timeout = aiohttp.ClientTimeout(total=30)
    # ruleid: aiohttp-missing-trust-env
    async with aiohttp.ClientSession(timeout=timeout) as session:
        pass


async def test_no_trust_env_assigned():
    # ruleid: aiohttp-missing-trust-env
    session = aiohttp.ClientSession()


async def test_no_trust_env_bare_import():
    # ruleid: aiohttp-missing-trust-env
    async with ClientSession() as session:
        pass


async def test_no_trust_env_bare_import_with_kwargs():
    # ruleid: aiohttp-missing-trust-env
    session = ClientSession(headers={"X-Custom": "value"})


# ============================================================
# Should flag: trust_env explicitly set to False (external call
# should go through proxy — use nosemgrep to opt out)
# ============================================================


async def test_trust_env_false():
    # ruleid: aiohttp-missing-trust-env
    async with aiohttp.ClientSession(trust_env=False) as session:
        pass


async def test_trust_env_false_bare():
    # ruleid: aiohttp-missing-trust-env
    session = ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=5))


# ============================================================
# Should NOT flag: trust_env=True
# ============================================================


async def test_trust_env_true():
    # ok: aiohttp-missing-trust-env
    async with aiohttp.ClientSession(trust_env=True) as session:
        pass


async def test_trust_env_true_with_kwargs():
    timeout = aiohttp.ClientTimeout(total=30)
    # ok: aiohttp-missing-trust-env
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        pass


async def test_trust_env_true_assigned():
    # ok: aiohttp-missing-trust-env
    session = aiohttp.ClientSession(trust_env=True)


async def test_trust_env_true_bare_import():
    # ok: aiohttp-missing-trust-env
    async with ClientSession(trust_env=True) as session:
        pass


async def test_trust_env_true_kwarg_order():
    # ok: aiohttp-missing-trust-env
    session = ClientSession(headers={"X-Custom": "value"}, trust_env=True)
