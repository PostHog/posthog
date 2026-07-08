"""Multi-processing worker initialization.

Keep this module without any imports to avoid conflicts when bootstrapping
multiprocessing workers."""


def init_worker():
    import django

    django.setup()
