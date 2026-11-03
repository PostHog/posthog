import { waitFor } from '@testing-library/react'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasPickerLogic } from './canvasPickerLogic'

const CANVAS_A = '0192f1c4-7b2e-7d3a-9f00-00000000000a'
const CANVAS_B = '0192f1c4-7b2e-7d3a-9f00-00000000000b'

describe('canvasPickerLogic', () => {
    let logic: ReturnType<typeof canvasPickerLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/': ({ params }) =>
                    params.id === CANVAS_B
                        ? [500, { detail: 'boom' }]
                        : [200, { id: params.id, name: `Canvas ${params.id}`, kind: 'freeform' }],
            },
        })
        silenceKeaLoadersErrors()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
    })

    it('clears the selection error when the viewer picks back a canvas that already loaded', async () => {
        logic = canvasPickerLogic({ pickerKey: 'modal' })
        logic.mount()

        logic.actions.ensureSelectedLoaded(CANVAS_A)
        await waitFor(() => expect(logic.values.selectedCanvas?.id).toBe(CANVAS_A))

        logic.actions.ensureSelectedLoaded(CANVAS_B)
        await waitFor(() => expect(logic.values.selectedCanvasFailed).toBe(true))

        logic.actions.ensureSelectedLoaded(CANVAS_A)
        expect(logic.values.selectedCanvasFailed).toBe(false)
        expect(logic.values.selectedCanvas?.id).toBe(CANVAS_A)
    })
})
