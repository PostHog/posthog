import jwt from 'jsonwebtoken'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-classify.template'

describe('JEV classification workflow step', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'classify' }
    const inputs = {
        text: '{event.properties.message}',
        instructions: 'Choose the sentiment of the text.',
        labels: { positive: 'Positive sentiment', negative: 'Negative sentiment' },
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('renders event text and stages a request scoped to the workflow project', async () => {
        const response = await tester.invoke(
            inputs,
            { event: { properties: { message: 'I like this feature.' } } },
            workflowOptions
        )
        expect(response.error).toBeUndefined()
        const params = response.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_classifications\/$/)
        expect(parseJSON(params.body!)).toEqual({ ...inputs, text: 'I like this feature.' })
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(
            params.headers!.Authorization.replace('Bearer ', ''),
            'local-dev-workflow-classification-jwt',
            {
                audience: 'posthog:workflows:classification',
                algorithms: ['HS256'],
            }
        ) as jwt.JwtPayload
        expect(claims.team_id).toBe(1)
        expect(claims.hog_flow_id).toBe(workflowOptions.hogFlow.id)
    })

    it('returns the label and probabilities for the output variable', async () => {
        let response = await tester.invoke({ ...inputs, text: 'Example text' }, undefined, workflowOptions)
        const classification = { label: 'positive', confidence: 0.9, probabilities: { positive: 0.9, negative: 0.1 } }
        response = await tester.invokeFetchResponse(response.invocation, { status: 200, body: classification })
        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual(classification)
        expect(response.finished).toBe(true)
    })

    it('refuses to spend classifications outside a workflow', async () => {
        const response = await tester.invoke({ ...inputs, text: 'Example text' })
        expect(response.error).toMatch(/inside a workflow/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it.each([403, 502, 503])('fails the step instead of returning a label on HTTP %i', async (status) => {
        let response = await tester.invoke({ ...inputs, text: 'Example text' }, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status,
            body: { detail: 'Classification unavailable.' },
        })
        expect(response.error).toContain('Classification unavailable.')
    })
})
