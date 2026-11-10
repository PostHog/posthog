import { FaultList } from './faults'

describe('FaultList', () => {
    it('applies a share at every crossing even where the product rounds just below it', () => {
        const faults = new FaultList()
        faults.add({ name: 'ses.reject', answer: { kind: 'drop-connection' }, dose: { share: 0.58 } })

        const applied = Array.from({ length: 50 }, () => faults.take([])).filter(Boolean)

        expect(applied).toHaveLength(29)
    })
})
