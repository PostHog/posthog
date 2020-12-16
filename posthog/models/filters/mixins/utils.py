from functools import lru_cache


# can't use cached_property directly from functools because of 3.7 compatibilty
def cached_property(func):
    return property(lru_cache(maxsize=1)(func))


def include_dict(f):
    f.include_dict = True
    return f
