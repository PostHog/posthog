import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { resolveProjectId } from './config.js'

describe('resolveProjectId', () => {
    it('returns the existing projectId when the token has no scoped teams', () => {
        assert.equal(resolveProjectId(undefined, '123'), '123')
        assert.equal(resolveProjectId([], '123'), '123')
    })

    it('returns undefined when no existing projectId and no scope is provided', () => {
        assert.equal(resolveProjectId(undefined, undefined), undefined)
        assert.equal(resolveProjectId([], undefined), undefined)
    })

    it('auto-picks the only scoped team when no existing projectId is set', () => {
        assert.equal(resolveProjectId([456], undefined), '456')
    })

    it('clears a stale projectId that is not in the new scoped_teams (single team)', () => {
        // This is the original bug: token scopes team 456 but config still says 123.
        // The new token can't access 123, so we must drop it and pick 456 instead.
        assert.equal(resolveProjectId([456], '123'), '456')
    })

    it('clears a stale projectId that is not in the new scoped_teams (multi team)', () => {
        // Multi-team grant with the old project not in scope — caller must re-prompt.
        assert.equal(resolveProjectId([456, 789], '123'), undefined)
    })

    it('keeps the existing projectId when it is still inside the scoped set', () => {
        assert.equal(resolveProjectId([123, 999], '123'), '123')
    })

    it('treats scoped_teams as numeric and matches against the string projectId', () => {
        assert.equal(resolveProjectId([123], '123'), '123')
        assert.equal(resolveProjectId([124], '123'), '124')
    })
})
