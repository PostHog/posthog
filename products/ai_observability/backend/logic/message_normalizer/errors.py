class RecipeCompileError(ValueError):
    pass


class RecipeRuntimeError(RuntimeError):
    pass


class RecipeTimeoutError(RecipeRuntimeError):
    pass


class RecipeOutputLimitError(RecipeRuntimeError):
    pass
