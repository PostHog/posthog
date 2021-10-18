from django.core.cache import cache


def clear_cache():
    """
    We don't want tests to be polluted by cache from other tests. It is not
    guaranteed that they will be caching with non-conflicting keys.
    
    We are using the `Filter` object as a source of key, but this does not take
    into account that the underlying event data may have changed etc.
    """
    cache.clear()