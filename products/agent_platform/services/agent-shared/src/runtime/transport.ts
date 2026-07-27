/**
 * Transport / admission types. A transport (Slack, Discord, HTTP, …) proves its
 * own authenticity and emits a `TransportClaim` — who the sender is *per that
 * transport*. That claim is NOT an authorising identity: the agent's
 * authoritative provider decides, via `AdmissionService`, whether it's enough to
 * run, must be upgraded with a link, or carries a verifiable per-request bearer.
 */

/** What a transport asserts about an inbound request. */
export interface TransportClaim {
    /** Stable transport id ('slack' | 'discord' | 'http' | …); also the
     *  `principal_kind` of the transport AgentUser. */
    transport: string
    /** Stable per-transport sender id (the transport AgentUser `principal_id`),
     *  e.g. 'T01:U01' for Slack, the JWT `sub` for http-jwt. */
    subjectId: string
    /** A per-request credential the transport already carries (HTTP bearer / JWT)
     *  that the authoritative provider MAY verify inline to admit without a link. */
    bearer?: { token: string }
    /** Attributes the transport vouches for (display name, email hint). Advisory
     *  only — never an authorisation input. Stored as AgentUser metadata. */
    attributes?: Record<string, unknown>
}

/** A verified, authoritative identity — the source of truth for "who is this". */
export interface VerifiedIdentity {
    /** Authoritative provider id that proved this. */
    provider: string
    /** The provider's stable subject (PostHog user uuid, Google sub, …). */
    subject: string
    /** Our canonical identity row id (an AgentUser keyed on provider+subject). */
    canonicalId: string
    /** The transport AgentUser bound to the canonical identity (per-message sender). */
    transportAgentUserId: string
}

/** A link to send a user so they can authenticate with the authoritative provider. */
export interface AuthBlock {
    provider: string
    authorizeUrl: string
}

export type AdmissionResult =
    /** No authoritative provider — the transport claim IS the identity (public /
     *  passthrough agents, today's behaviour). */
    | { kind: 'passthrough'; transportAgentUserId: string }
    /** Verified — safe to enqueue a session. */
    | { kind: 'admitted'; identity: VerifiedIdentity }
    /** Not yet authenticated — deliver this block and do NOT enqueue. */
    | ({ kind: 'auth_required' } & AuthBlock)
    /** Provider/config error — fail closed (do NOT enqueue). */
    | { kind: 'error'; reason: string }

/**
 * A generic entrypoint. Extracts a claim from a raw inbound request and delivers
 * an auth block back over its own channel. Implemented per host in the ingress
 * (Slack ephemeral/DM, HTTP response body, …); the admission engine itself is
 * transport-agnostic.
 */
export interface Transport<TRequest = unknown> {
    readonly id: string
    /** Extract the claim, or null if the request isn't a valid invocation. */
    claim(req: TRequest): TransportClaim | null
    /** Deliver an auth block privately to the claimant over this transport. */
    deliverAuthBlock(req: TRequest, block: AuthBlock): Promise<void>
}
