from enum import StrEnum


class ParserMode(StrEnum):
    CPP_ONLY = "cpp_only"
    CPP_WITH_RUST_SHADOW = "cpp_with_rust_shadow"
    CPP_WITH_RUST_PY_SHADOW = "cpp_with_rust_py_shadow"
    RUST_WITH_CPP_SHADOW = "rust_with_cpp_shadow"
    RUST_ONLY = "rust_only"
    RUST_PY_ONLY = "rust_py_only"
    RUST_PY_WITH_CPP_SHADOW = "rust_py_with_cpp_shadow"
