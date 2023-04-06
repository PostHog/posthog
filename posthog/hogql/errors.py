class HogQLException(ValueError):
    pass


class ResolverException(HogQLException):
    pass


class ParserException(HogQLException):
    pass


class NotImplementedException(HogQLException):
    pass
