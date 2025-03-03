import copy
from dataclasses import dataclass, field
from itertools import permutations
from typing import Optional, Self

from posthog.hogql import ast

from posthog.hogql.errors import QueryError


BaseT = ast.ConstantType
UnknownT = ast.UnknownType

# The AST doesn't seem to know about higher-kinded functions, at least in any type level
# way, so we have to define our own types for this, and make it match UnknownType in the
# signature lookup code.
@dataclass()
class AnonFunctionT:
    argtypes: list[BaseT | Self] = field(default_factory=list)
    returns: BaseT | Self | None = None

AnyKnownT = BaseT | AnonFunctionT
ArgList = list[AnyKnownT] | tuple[list[AnyKnownT], AnyKnownT]
Returns = AnyKnownT | None
ResolvedSignature = tuple[str, ArgList, Returns]
Overloads = list[ResolvedSignature]

# Lists are unhashable so we have to do it this way I guess. Slow
# but only done on startup so not the end of the world
def collapse_sigs(sigs: list[ResolvedSignature]) -> list[ResolvedSignature]:
    collapsed = []

    for pairs in permutations(sigs, 2):
        if pairs[0][1] == pairs[1][1] and pairs[0][2] != pairs[1][2]:
            message = f"Indeterminate function signature for {pairs[0][0]} with args {pairs[0][1]}. Cannot between returning {pairs[0][2]} and {pairs[1][2]}"
            raise ValueError(message)

    for sig in sigs:
        if sig not in collapsed:
            collapsed.append(sig)

    return collapsed

def remove_collisions(sigs: list[tuple[ArgList, Returns]]) -> list[tuple[ArgList, Returns]]:
    unique_sigs = []
    for sig in sigs:
        if sig not in unique_sigs:
            unique_sigs.append(sig)

    return unique_sigs


@dataclass()
class HogQLFunctionMeta:
    name: str
    min_params: int = 0
    max_params: Optional[int] = 0
    aggregate: bool = False
    tz_aware: bool = False
    """Whether the function is timezone-aware. This means the project timezone will be appended as the last arg."""
    case_sensitive: bool = True
    """Not all ClickHouse functions are case-insensitive. See https://clickhouse.com/docs/en/sql-reference/syntax#keywords."""
    signatures: Overloads = field(default_factory=lambda: [])
    """Signatures allow for specifying the types of the arguments and the return type of the function."""
    suffix_args: Optional[list[ast.Constant]] = None
    """Additional arguments that are added to the end of the arguments provided by the caller"""


    @property
    def max_args(self) -> Optional[int]:
        longest_sig_seen = 0
        for _, args, _ in self.signatures:
            if isinstance(args, tuple):
                # This is a variadic argument list
                return None
            longest_sig_seen = max(longest_sig_seen, len(args))
        return longest_sig_seen

    @property
    def min_args(self) -> int:
        if len(self.signatures) == 0:
            return 0

        shortest_sig_seen = 10000 # sure, that'll do
        for _, args, _ in self.signatures:
            if isinstance(args, tuple):
                fixed_list = args[0]
                # NOTE - this assumes, if the function is variadic but requires at least 1 argument,
                # that argument is put into the fixed list.
                shortest_sig_seen = min(shortest_sig_seen, len(fixed_list))
            else:
                shortest_sig_seen = min(shortest_sig_seen, len(args))
        return shortest_sig_seen
    
    @property
    def is_variadic(self) -> bool:
        return any(isinstance(args, tuple) for _, args, _ in self.signatures)

    def clickhouse_name(self, input_args: list[BaseT], permissive_matching: bool = True, function_term: str = "function") -> str:
        return self._find_matching_sig(input_args, permissive_matching, function_term)[0]

    def return_type(self, input_args: list[BaseT], permissive_matching: bool = True, function_term: str = "function") -> BaseT | None:
        found = self._find_matching_sig(input_args, permissive_matching, function_term)[2]
        if not isinstance(found, BaseT):
            return UnknownT() # We don't support non-constant return types yet
        return found

    def _find_matching_sig(self, input_args: list[BaseT], permissive_matching: bool = True, function_term: str = "function") -> ResolvedSignature:
        _assert_arg_length(input_args, self.min_args, self.max_args, self.name, function_term=function_term, argument_term="argument")


        for sig in self.signatures:
            _, sig_args, _ = sig
            if isinstance(sig_args, tuple):
                fixed = sig_args[0]
                varying = sig_args[1]
            else:
                fixed = sig_args
                varying = None

            if len(input_args) < len(fixed):
                continue

            if varying is None and len(input_args) > len(fixed):
                continue

            all_fixed_match = all(
                isinstance(sig_arg_type, UnknownT)
                or isinstance(arg_type, UnknownT) and isinstance(sig_arg_type, AnonFunctionT) # TODO - for now the ast doesn't know about function types
                or isinstance(arg_type, sig_arg_type.__class__)
                or (permissive_matching and isinstance(arg_type, UnknownT))
                for arg_type, sig_arg_type in zip(input_args, fixed)
            )

            if not all_fixed_match:
                continue

            if varying is not None:
                if not all(
                    isinstance(arg_type, varying.__class__)
                    or (permissive_matching and isinstance(arg_type, UnknownT))
                    or isinstance(arg_type, UnknownT) and isinstance(varying, AnonFunctionT) # TODO - for now the ast doesn't know about function types
                    for arg_type in input_args[len(fixed):]
                ):
                    continue

            return sig

        raise QueryError(f"Could not find a matching signature for function '{self.name}' with arguments {', '.join(str(arg) for arg in input_args)}")

def assert_param_arg_length(
    args: list[BaseT],
    meta: HogQLFunctionMeta,
    function_name: str,
    function_term="function",
):
    _assert_arg_length(args, meta.min_params, meta.max_params, function_name, function_term=function_term, argument_term="parameter")

def _assert_arg_length(
    args: list[BaseT],
    min_args: int,
    max_args: Optional[int],
    function_name: str,
    function_term="function",
    argument_term="argument",
):
    too_few = len(args) < min_args
    too_many = max_args is not None and len(args) > max_args
    if min_args == max_args and (too_few or too_many):
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_few:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at least {min_args} {argument_term}{'s' if min_args != 1 else ''}, found {len(args)}"
        )
    if too_many:
        raise QueryError(
            f"{function_term.capitalize()} '{function_name}' expects at most {min_args} {argument_term}{'s' if max_args != 1 else ''}, found {len(args)}"
        )

def get_expr_types(args: list[ast.Expr], context: ast.HogQLContext) -> list[BaseT]:
    return [arg.type.resolve_constant_type(context) if arg.type else UnknownT() for arg in args]

# TODO - make this an function on the HogQLFunctionMeta class
def find_return_type(
    args: list[BaseT],
    meta: HogQLFunctionMeta,
    *,
    function_term="function",
    permissive_match,
    raise_on_no_match,
) -> BaseT | None:
    _assert_arg_length(args, meta.min_args, meta.max_args, meta.name, function_term=function_term, argument_term="argument")

    # If we don't have a sig, we can't know the return type
    # TODO - uncomment this once every function has a signature
    if not meta.signatures:
        return UnknownT()

    try:
        returned = meta.return_type(args, permissive_match, function_term=function_term)
    except QueryError as e:
        if raise_on_no_match:
            raise e
        return UnknownT()

    return returned

@dataclass
class Buildable:
    name: str
    overloads: Overloads
    tz_aware: bool = False
    aggregate: bool = False
    case_insensitive: bool = False
    min_params: int = 0
    max_params: Optional[int] = None
    suffix_args: Optional[list[ast.Constant]] = None

    def finish(self) -> HogQLFunctionMeta:
        return HogQLFunctionMeta(
            name=self.name,
            min_params=self.min_params,
            max_params=self.max_params,
            aggregate=self.aggregate,
            tz_aware=self.tz_aware,
            case_sensitive=not self.case_insensitive,
            signatures=self.overloads,
        )
    
    def is_tz_aware(self) -> Self:
        self.tz_aware = True
        return self
    
    def is_aggregate(self) -> Self:
        self.aggregate = True
        return self
    
    def is_case_insensitive(self) -> Self:
        self.case_insensitive = True
        return self

    def with_params(self, min_params: int, max_params: Optional[int] = None) -> Self:
        self.min_params = min_params
        self.max_params = max_params
        return self

    def with_suffix_args(self, suffix: list[ast.Constant]) -> Self:
        self.suffix_args = suffix
        return self

@dataclass
class Paramaterised:
    def get_generic_args(self) -> list[str]:
        raise NotImplementedError("Paramaterised.get_generic_args not implemented")

    def instantiate(self, lookup_table: dict[str, list[AnyKnownT]]) -> list[AnyKnownT]:
        raise NotImplementedError("Paramaterised.resolve_generics not implemented")

    def partially_resolve(self, part: str, to: AnyKnownT) -> Self | AnyKnownT:
        raise NotImplementedError("Paramaterised.partially_resolve not implemented")

GenericArg = AnyKnownT | str | Paramaterised
GenericArgList = list[GenericArg] | tuple[list[GenericArg], GenericArg]
GenericReturn = AnyKnownT | None

@dataclass
class GenericArray(Paramaterised):
    inner: GenericArg

    def get_generic_args(self) -> list[str]:
        if isinstance(self.inner, str):
            return [self.inner]
        elif isinstance(self.inner, Paramaterised):
            return self.inner.get_generic_args()
        else:
            return []

    def instantiate(self, lookup_table: dict[str, list[AnyKnownT]]) -> list[AnyKnownT]:
        if isinstance(self.inner, str):
            inners = lookup_table[self.inner]
        elif isinstance(self.inner, Paramaterised):
            inners = self.inner.instantiate(lookup_table)
        else:
            inners = [self.inner]
        # TODO - the UnknownType here is not great, bet we'd either have to use our own array type or modify
        # the ast array type to be able to handle AnyKnownType if we did anything else.
        return [ast.ArrayType(item_type=t) if isinstance(t, BaseT) else UnknownT() for t in inners]

    def partially_resolve(self, part: str, to: AnyKnownT) -> Self | AnyKnownT:
        if isinstance(self.inner, str):
            if self.inner == part:
                inner = to if isinstance(to, BaseT) else UnknownT()
                return ast.ArrayType(item_type=inner)
            return self
        elif isinstance(self.inner, Paramaterised):
            res = copy.deepcopy(self)
            res.inner = self.inner.partially_resolve(part, to)
            if isinstance(res.inner, BaseT):
                return ast.ArrayType(item_type=res.inner)
            return res
        else:
            return self

@dataclass
class GenericFunction(Paramaterised):
    param_list: list[GenericArg] = field(default_factory=list)
    return_type: GenericReturn = None

    def get_generic_args(self) -> list[str]:
        acc = []
        for p in self.param_list:
            if isinstance(p, str):
                acc.append(p)
            elif isinstance(p, Paramaterised):
                acc.extend(p.get_generic_args())
        if isinstance(self.return_type, str):
            acc.append(self.return_type)
        elif isinstance(self.return_type, Paramaterised):
            acc.extend(self.return_type.get_generic_args())
        return acc

    def instantiate(self, lookup_table: dict[str, list[AnyKnownT]]) -> list[AnyKnownT]:
        generics = self.get_generic_args()
        # TODO - something something covariant, idk
        across: dict[str, list[GenericArg]] = {k: v for k, v in lookup_table.items() if k in generics}
        sig = GenericSig().takes(*self.param_list).returns(self.return_type).across(**across)
        res = []
        for resolved in sig._resolve_generics():
            args, returns = resolved
            if isinstance(args, tuple):
                fixed, varying = args
            else:
                fixed = args
                varying = None

            argtypes = [x if isinstance(x, BaseT) else UnknownT() for x in fixed]

            # TODO - support trailing args in anonymous functions
            varying = varying if isinstance(varying, BaseT) else UnknownT() if varying else None
            if varying:
                argtypes.append(varying) # Function expressions
            
            returns = returns if isinstance(returns, BaseT) else UnknownT() if returns else None
            res.append(AnonFunctionT(argtypes=argtypes, returns=returns))
            
        return res


    def partially_resolve(self, part: str, to: AnyKnownT) -> Self | AnyKnownT:
        res = copy.deepcopy(self)
        new_params = []
        for p in self.param_list:
            if isinstance(p, str) and p == part:
                new_params.append(to)
            elif isinstance(p, Paramaterised):
                new_params.append(p.partially_resolve(part, to))
            else:
                new_params.append(p)

        if self.return_type:
            if isinstance(self.return_type, str) and self.return_type == part:
                res.return_type = to
            elif isinstance(self.return_type, Paramaterised):
                res.return_type = self.return_type.partially_resolve(part, to)

        if all(isinstance(x, AnyKnownT) for x in new_params) and isinstance(res.return_type, AnyKnownT):
            return AnonFunctionT(argtypes=new_params, returns=res.return_type)
        return res

    def takes(self, *args: GenericArg) -> Self:
        res = copy.deepcopy(self)
        res.param_list = list(args)
        return res
    
    def returns(self, ret: GenericReturn) -> Self:
        res = copy.deepcopy(self)
        res.return_type = ret
        return res


@dataclass
class GenericSig:
    generics: dict[str, list[GenericArg]] = field(default_factory=dict)
    args: GenericArgList = field(default_factory=list)
    ret: GenericReturn = None

    def _resolve_generics(self) -> list[tuple[ArgList, Returns]]:
        flattened = self._flatten_generics()
        #print(f"Flattened generics: {flattened}")

        packed_vals: list[list[GenericArg | None]] = []
        if isinstance(self.args, tuple):
            fixed, varying = self.args
        else:
            fixed = self.args
            varying = None

        packed_vals.append([*fixed, varying, self.ret])

        for name, types in flattened.items():
            next_packed_set = []
            for packed in packed_vals:
                for t in types:
                    replaced = []
                    for x in packed:
                        if x == name:
                            replaced.append(t)
                        elif isinstance(x, Paramaterised):
                            replaced.append(x.partially_resolve(name, t))
                        else:
                            replaced.append(x)
                    if replaced not in next_packed_set:
                        next_packed_set.append(replaced)
            packed_vals = next_packed_set

        full_sigs: list[tuple[ArgList, Returns]] = []
        for packed in packed_vals:
            unresolved = [x for x in packed if not isinstance(x, AnyKnownT) and x is not None]
            if unresolved:
                raise ValueError(f"Generic arguments {unresolved} are not resolved")

            fixed = [x for x in packed[:-2] if isinstance(x, AnyKnownT) and x is not None]
            varying = packed[-2] if isinstance(packed[-2], AnyKnownT) else None
            ret = packed[-1] if isinstance(packed[-1], AnyKnownT) else None

            if varying:
                full_sigs.append(((fixed, varying), ret))
            else:
                full_sigs.append((fixed, ret))

        # Generics easily lead to duplicate sigs, so we dedupe here
        resolved = remove_collisions(full_sigs)
        return resolved

    def _flatten_generics(self) -> dict[str, list[AnyKnownT]]:
        #print(f"Flattening generics {self.generics}")
        if not self.generics:
            return {}
        #print(f"Flattening generics {self.generics}")
        acc = {}
        for start in self.generics.keys():
            self._recursively_flatten_generics(start, acc, [])
        return acc

    def _recursively_flatten_generics(self, next: str, acc: dict[str, list[AnyKnownT]] , stack: list[str]):
        if not self.generics:
            return acc

        if next in stack:
            raise ValueError(f"Generic {next} is recursive")
        
        if next not in self.generics:
            raise ValueError(f"Generic {next} is not defined")
        
        if next not in acc:
            acc[next] = []

        for t in self.generics[next]:
            if isinstance(t, str): # This is a generic referencing another generic
                stack.append(next)
                self._recursively_flatten_generics(t, acc, stack)
                stack.pop()
                acc[next].extend(acc[t])
            elif isinstance(t, Paramaterised):
                inner_generics = t.get_generic_args()
                # We detour to ensure all the inner T's are resolved before trying to resolve our
                # parametrised type
                for inner in inner_generics:
                    stack.append(inner)
                    self._recursively_flatten_generics(inner, acc, stack)
                    stack.pop()
                acc[next].extend(t.instantiate(acc))
            else:
                acc[next].append(t)

        types = []
        for t in acc[next]:
            if t not in types:
                types.append(t)

        acc[next] = types
        #print(f"Accumulated generics for {next}: {acc[next]}")
        return acc

    def takes(self, *args: GenericArg) -> Self:
        res = copy.deepcopy(self)
        res.args = list(args)
        return res
    
    def trailing(self, arg: GenericArg) -> Self:
        res = copy.deepcopy(self)
        if isinstance(res.args, tuple):
            res.args = (res.args[0], arg)
        else:
            res.args = (res.args, arg)
        return res
    
    def returns(self, ret: GenericReturn) -> Self:
        res = copy.deepcopy(self)
        res.ret = ret
        return res
    
    def across(self, **gens: list[GenericArg] | GenericArg) -> Self:
        res = copy.deepcopy(self)
        res.generics = {k: v if isinstance(v, list) else [v] for k, v in gens.items()}
        return res

@dataclass
class Stub:
    name: str
    sig: GenericSig = field(default_factory=GenericSig)

    def resolve(self) -> list[ResolvedSignature]:
        return [(self.name, args, returns) for args, returns in self.sig._resolve_generics()]


@dataclass
class MapsTo:
    name: str
    overloads: list[ResolvedSignature] = field(default_factory=list)

    def exposes(self, *sigs: Stub) -> Self:
        resolved: list[ResolvedSignature] = []
        for s in sigs:
            resolved.extend(s.resolve())
        # check for collisions in the signature lists (two signatures with the same args)
        self.overloads = collapse_sigs(self.overloads + resolved)
        return self


    def compose(self) -> Buildable: 
        return Buildable(
            name=self.name,
            overloads=self.overloads
        )

def hql_fn(name: str) -> MapsTo:
    return MapsTo(name=name)

def FN(name: str, *sigs: GenericSig) -> list[Stub]:
    return [Stub(name=name, sig=sig) for sig in sigs]

def ACROSS(**gens: list[GenericArg] | GenericArg) -> GenericSig:
    return GenericSig().across(**gens)

def TAKING(*args: GenericArg) -> GenericSig:
    return GenericSig().takes(*args)

def TWO(arg: GenericArg) -> list[GenericArg]:
    return [arg, arg]

def AT_LEAST(count: int, arg: GenericArg) -> GenericSig:
    return GenericSig().takes(*[arg] * (count-1)).trailing(arg)

def ANY() -> list[GenericArg]:
    return [ast.StringType(), ast.BooleanType(), ast.DateType(), ast.DateTimeType(), ast.UUIDType(), ast.ArrayType(item_type=UnknownT()), ast.TupleType(item_types=[UnknownT()]), ast.IntegerType(), ast.FloatType(), ast.IntervalType(), ast.DecimalType()]

def ANY_NUM() -> list[GenericArg]:
    return [ast.IntegerType(), ast.FloatType(), ast.DecimalType()]

def ANY_NUMERIC_TUPLE() -> list[GenericArg]:
    return [ast.TupleType(item_types=[ast.IntegerType()]), ast.TupleType(item_types=[ast.FloatType()]), ast.TupleType(item_types=[ast.DecimalType()])]

def ARRAY_OR_STR() -> list[GenericArg]:
    # TODO - the array type here should be generic, instead of just unknown... to address when we've got a better handle on generics
    return [ast.ArrayType(item_type=UnknownT()), ast.StringType()]

def TAKES_BETWEEN(low: int, high: int, arg: GenericArg, ret: GenericReturn = None) -> list[GenericSig]:
    return [GenericSig().takes(*[arg] * i).returns(ret) for i in range(low, high+1)]

def IN_ANY_ORDER(sig: GenericSig) -> list[GenericSig]:
    old_args = sig.args
    if isinstance(old_args, tuple):
        fixed, varying = old_args
    else:
        fixed = old_args
        varying = None

    new_sigs = []
    for perm in permutations(fixed):
        new_args = list(perm)
        if varying:
            new_sig = sig.takes(*new_args).trailing(varying)
        else:
            new_sig = sig.takes(*new_args)
        new_sigs.append(new_sig)

    return new_sigs

def ARRAY_OF(arg: GenericArg) -> GenericArray:
    return GenericArray(inner=arg)