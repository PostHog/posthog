from django.db import connection
from django.db.backends.utils import CursorDebugWrapper
from structlog import get_logger

logger = get_logger(__name__)

import urllib.parse

KEY_VALUE_DELIMITER = ','

def generate_sql_comment(**meta):
    """
    Return a SQL comment with comma delimited key=value pairs created from
    **meta kwargs.
    """
    if not meta:  # No entries added.
        return ''

    # Sort the keywords to ensure that caching works and that testing is
    # deterministic. It eases visual inspection as well.
    return ' /*' + KEY_VALUE_DELIMITER.join(
        '{}={!r}'.format(url_quote(key), url_quote(value)) for key, value in sorted(meta.items())
        if value is not None
    ) + '*/'


def url_quote(s):
    if not isinstance(s, (str, bytes)):
        return s
    quoted = urllib.parse.quote(s)
    # Since SQL uses '%' as a keyword, '%' is a by-product of url quoting
    # e.g. foo,bar --> foo%2Cbar
    # thus in our quoting, we need to escape it too to finally give
    #      foo,bar --> foo%%2Cbar
    return quoted.replace('%', '%%')


class SqlCommenterMiddleware:
    """
    Middleware to append a comment to each database query with details about
    the framework and the execution context.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with connection.execute_wrapper(QueryWrapper(request)):
            return self.get_response(request)


class QueryWrapper:
    def __init__(self, request):
        self.request = request

    def __call__(self, execute, sql, params, many, context):

        resolver_match = self.request.resolver_match

        sql_comment = generate_sql_comment(
            # Information about the controller.
            controller=(resolver_match.view_name or None) if resolver_match else None,
            # route is the pattern that matched a request with a controller i.e. the regex
            # See https://docs.djangoproject.com/en/stable/ref/urlresolvers/#django.urls.ResolverMatch.route

            route=(resolver_match.route or None) if resolver_match else None,

            # app_name is the application namespace for the URL pattern that matches the URL.
            # See https://docs.djangoproject.com/en/stable/ref/urlresolvers/#django.urls.ResolverMatch.app_name
            app_name=(resolver_match.app_name or None) if resolver_match else None,
        )

        sql += sql_comment

        # Add the query to the query log if debugging.
        if context['cursor'].__class__ is CursorDebugWrapper:
            context['connection'].queries_log.append(sql)

        return execute(sql, params, many, context)
