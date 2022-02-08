from django.utils.cache import add_never_cache_headers


# Work around cloudflare by default caching csv files
class CSVNeverCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith("csv"):
            add_never_cache_headers(response)
        return response
