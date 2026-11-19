import { parseWorkloadAttribution, workloadActorLabel } from './parseWorkloadAttribution'

describe('parseWorkloadAttribution', () => {
    const workloadTrigger = {
        job_type: 'workload',
        job_id: 'policy-1',
        payload: {
            provider_name: 'Example CI',
            subject_name: 'acme/web',
            claims: { workflow: 'deploy.yml', ref: 'refs/heads/main', run_id: 1234 },
            claim_labels: { workflow: 'Workflow', ref: 'Branch or tag' },
            run_url: 'https://ci.example.com/acme/web/runs/1234',
            policy_name: 'Production deploys',
        },
    }

    it.each([
        ['no trigger', null, null],
        ['an agent trigger', { job_type: 'agent', job_id: 'task', payload: { subject_name: 'acme/web' } }, null],
        ['a workload trigger without an actor label', workloadTrigger, 'Example CI · acme/web'],
        [
            'a workload trigger with an actor label',
            { ...workloadTrigger, payload: { ...workloadTrigger.payload, actor_label: 'acme/web · nightly' } },
            'Example CI · acme/web · nightly',
        ],
    ])('reads %s', (_name, trigger, expectedLabel) => {
        const attribution = parseWorkloadAttribution({ detail: { merge: null, changes: null, name: null, trigger } })

        expect(attribution ? workloadActorLabel(attribution) : null).toEqual(expectedLabel)
    })

    it('labels the recorded claims and skips values that are not text', () => {
        const attribution = parseWorkloadAttribution({
            detail: { merge: null, changes: null, name: null, trigger: workloadTrigger },
        })

        expect(attribution?.claims).toEqual([
            { name: 'workflow', label: 'Workflow', value: 'deploy.yml' },
            { name: 'ref', label: 'Branch or tag', value: 'refs/heads/main' },
        ])
    })

    it('drops a run link that is not https', () => {
        const attribution = parseWorkloadAttribution({
            detail: {
                merge: null,
                changes: null,
                name: null,
                trigger: {
                    ...workloadTrigger,
                    payload: { ...workloadTrigger.payload, run_url: 'javascript:alert(1)' },
                },
            },
        })

        expect(attribution?.runUrl).toBeNull()
    })
})
