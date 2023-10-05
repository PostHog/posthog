from distutils.core import setup, Extension
import platform

system = platform.system()
if system not in ("Darwin", "Linux"):
    raise Exception("Only Linux and macOS are supported by hogql_parser")

is_macos = system == "Darwin"

module = Extension(
    "hogql_parser",
    sources=[
        "HogQLLexer.cpp",
        "HogQLParser.cpp",
        "HogQLParserBaseVisitor.cpp",
        "HogQLParserVisitor.cpp",
        "error.cpp",
        "string.cpp",
        "parser.cpp",
    ],
    include_dirs=[
        "/opt/homebrew/include/" if is_macos else "/usr/include/",
        "/opt/homebrew/include/antlr4-runtime/"
        if is_macos
        else "/usr/local/include/antlr4-runtime/",
    ],
    library_dirs=[
        "/opt/homebrew/Cellar/boost/1.82.0_1/lib/"
        if is_macos == "Darwin"
        else "/usr/lib64/",
        "/opt/homebrew/Cellar/antlr4-cpp-runtime/4.13.1/lib/"
        if is_macos == "Darwin"
        else "/usr/local/lib/",
    ],
    libraries=["antlr4-runtime"],
    extra_compile_args=["-std=c++20"],
)

setup(
    name="hogql_parser",
    version="0.1",
    url="https://github.com/PostHog/posthog/tree/master/hogql_parser",
    author="PostHog Inc.",
    author_email="hey@posthog.com",
    maintainer="PostHog Inc.",
    maintainer_email="hey@posthog.com",
    description="HogQL parser for internal PostHog use",
    ext_modules=[module],
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.10",
    ],
)
