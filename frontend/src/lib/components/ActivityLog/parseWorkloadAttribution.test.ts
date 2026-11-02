import { workloadActorLabel, parseWorkloadAttribution } from './parseWorkloadAttribution'

describe('parseWorkloadAttribution', () => {
    const workloadTrigger = {
        job_type: 'workload',
        job_id: '1234',
        payload: {
            provider_name: 'Example CI',
            repository: 'acme/web',
            workflow: 'deploy.yml',
            run_id: '1234',
            run_url: 'https://ci.example.com/acme/web/runs/1234',
            policy_name: 'Production deploys',
        },
    }

    it.each([
        ['no trigger', null, null],
        ['an agent trigger', { job_type: 'agent', job_id: 'task', payload: { repository: 'acme/web' } }, null],
        ['a workload trigger without an actor label', workloadTrigger, 'Example CI · acme/web · deploy.yml run 1234'],
        [
            'a workload trigger with an actor label',
            { ...workloadTrigger, payload: { ...workloadTrigger.payload, actor_label: 'acme/web · nightly' } },
            'Example CI · acme/web · nightly',
        ],
    ])('reads %s', (_name, trigger, expectedLabel) => {
        const attribution = parseWorkloadAttribution({ detail: { merge: null, changes: null, name: null, trigger } })

        expect(attribution ? workloadActorLabel(attribution) : null).toEqual(expectedLabel)
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
