import { ciActorLabel, parseCIAttribution } from './parseCIAttribution'

describe('parseCIAttribution', () => {
    const ciTrigger = {
        job_type: 'ci',
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
        ['a CI trigger', ciTrigger, 'Example CI · acme/web · deploy.yml run 1234'],
    ])('reads %s', (_name, trigger, expectedLabel) => {
        const attribution = parseCIAttribution({ detail: { merge: null, changes: null, name: null, trigger } })

        expect(attribution ? ciActorLabel(attribution) : null).toEqual(expectedLabel)
    })

    it('drops a run link that is not https', () => {
        const attribution = parseCIAttribution({
            detail: {
                merge: null,
                changes: null,
                name: null,
                trigger: { ...ciTrigger, payload: { ...ciTrigger.payload, run_url: 'javascript:alert(1)' } },
            },
        })

        expect(attribution?.runUrl).toBeNull()
    })
})
