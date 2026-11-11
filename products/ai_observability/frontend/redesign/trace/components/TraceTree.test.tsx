import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { makeTraceResource } from '../adapter/testFixtures'
import { TraceTree } from './TraceTree'

describe('TraceTree', () => {
    it.each(['constructor', 'toString', '__proto__'])(
        'renders a step whose id %s names an object property without an eval marker',
        (id) => {
            const [root] = makeTraceResource().tree
            const { getByText, queryByLabelText } = render(
                <TraceTree
                    nodes={[{ ...root, id, name: id, children: [] }]}
                    selectedNodeId={null}
                    onSelectNode={() => {}}
                    onPrefetchNode={() => {}}
                    evalOutcomes={{}}
                />
            )

            expect(getByText(id)).toBeInTheDocument()
            expect(queryByLabelText(/^Evals/)).toBeNull()
        }
    )
})
