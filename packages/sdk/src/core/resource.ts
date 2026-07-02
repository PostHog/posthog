// Base class shared by every generated resource. Holds the transport and the
// scope resolver so generated methods can build project/org-scoped requests.

import { type HttpClient } from './http'
import { type ScopeResolver } from './scope'

export class Resource {
    protected readonly http: HttpClient
    protected readonly scope: ScopeResolver

    constructor(http: HttpClient, scope: ScopeResolver) {
        this.http = http
        this.scope = scope
    }
}
