import { projectPath } from './_posthog-api'

describe('projectPath', () => {
    it('targets the explicit project id the agent supplies', () => {
        // The data tools take an explicit `project_id` arg (resolved via
        // get_context / list-projects), never inferred from the agent or the
        // principal — so the path is built straight from that id and PostHog's
        // own access control enforces the caller's access.
        expect(projectPath(200, '/agent_applications/')).toBe('/api/projects/200/agent_applications/')
        expect(projectPath(1, '/query/')).toBe('/api/projects/1/query/')
    })
})
