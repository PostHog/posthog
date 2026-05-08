# Proto conventions and worked example

## Message conventions

- `int64` for IDs, timestamps (Unix millis), versions
- `bytes` for JSON data (not `string`) — properties, properties_last_updated_at, properties_last_operation, default_columns
- `optional` for nullable fields
- Stay at v1 for additive changes; bump to v2 only for breaking changes
- Never reuse field numbers after deletion
- Request messages: `<RpcName>Request`
- Response messages: `<RpcName>Response` (or a shared response type like `PersonsResponse` if appropriate)
- Include `ReadOptions read_options` field on read requests that need consistency control

## ReadOptions and consistency

```protobuf
// Already defined in common.proto — import it, don't redefine
import "personhog/types/v1/common.proto";

message YourReadRequest {
  int64 team_id = 1;
  // ... other fields ...
  ReadOptions read_options = N;  // last field
}
```

`ReadOptions` contains a `ConsistencyLevel` enum:

- `EVENTUAL` (default) — queries the replica pool
- `STRONG` — queries the primary pool (only meaningful for PersonData reads)

For NonPersonData, the replica handles consistency internally — the router always sends to replica regardless of consistency level.

## File organization

| Proto file                                    | Purpose                                                                       |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| `proto/personhog/types/v1/person.proto`       | Person, DistinctId messages and all person-related request/response types     |
| `proto/personhog/types/v1/group.proto`        | Group, GroupTypeMapping messages and all group-related request/response types |
| `proto/personhog/types/v1/cohort.proto`       | CohortMembership messages and cohort-related request/response types           |
| `proto/personhog/types/v1/feature_flag.proto` | HashKeyOverride messages and feature flag request/response types              |
| `proto/personhog/types/v1/common.proto`       | ReadOptions, ConsistencyLevel, TeamDistinctId — shared across domains         |
| `proto/personhog/service/v1/service.proto`    | PersonHogService — public API (what clients call)                             |
| `proto/personhog/replica/v1/replica.proto`    | PersonHogReplica — internal API (what the router calls)                       |
| `proto/personhog/leader/v1/leader.proto`      | PersonHogLeader — internal write API for person data                          |

## Worked example: adding GetPersonCount

### 1. Add messages to `types/v1/person.proto`

```protobuf
message GetPersonCountRequest {
  int64 team_id = 1;
  ReadOptions read_options = 2;
}

message GetPersonCountResponse {
  int64 count = 1;
}
```

### 2. Add RPC to `service/v1/service.proto`

```protobuf
service PersonHogService {
  // ... existing RPCs ...
  rpc GetPersonCount(personhog.types.v1.GetPersonCountRequest) returns (personhog.types.v1.GetPersonCountResponse);
}
```

### 3. Add RPC to `replica/v1/replica.proto`

```protobuf
service PersonHogReplica {
  // ... existing RPCs ...
  rpc GetPersonCount(personhog.types.v1.GetPersonCountRequest) returns (personhog.types.v1.GetPersonCountResponse);
}
```

The RPC signature **must be identical** in both service and replica protos.

### 4. Routing decision

This is a PersonData read → routed to replica for EVENTUAL, leader for STRONG.
In the router, use:

```rust
let route = route_request(
    DataCategory::PersonData,
    OperationType::Read,
    get_consistency(&request.read_options),
)?;
```

### 5. Python client wrapper (in client.py)

```python
def get_person_count(self, request: GetPersonCountRequest) -> GetPersonCountResponse:
    return self._stub.GetPersonCount(request, timeout=self._timeout)
```

### 6. Fake client method (in fake_client.py)

```python
def get_person_count(self, request: Any) -> Any:
    team_id = request.team_id
    count = sum(1 for (tid, _) in self._persons_by_id if tid == team_id)
    call = _Call("get_person_count", request)
    resp = person_pb2.GetPersonCountResponse(count=count)  # or however the response is built
    call.response = resp
    self.calls.append(call)
    return resp
```
