import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { BindLogic } from 'kea'
import { useLayoutEffect } from 'react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { NotebookScene } from './NotebookScene'
import { notebookSceneLogic } from './notebookSceneLogic'

jest.mock('./Notebook/migrations/migrate', () => {
    const actual = jest.requireActual('./Notebook/migrations/migrate')
    return {
        ...actual,
        migrate: jest.fn(async (notebook) => notebook),
    }
})

describe('NotebookScene', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api.notebooks, 'collabStream').mockResolvedValue(undefined as any)
        jest.spyOn(api.notebooks, 'create').mockReturnValue(new Promise(() => {}) as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('paints the loading state, not "not found", on the first commit of the new-notebook route', () => {
        // A layout effect runs on the first commit, before the browser paints and before the
        // mount effect that creates the notebook, so it sees the first frame the user would get.
        let firstCommit = ''
        function FirstCommitProbe(): null {
            useLayoutEffect(() => {
                firstCommit = document.body.innerHTML
            }, [])
            return null
        }

        render(
            <BindLogic logic={notebookSceneLogic} props={{ shortId: 'new' }}>
                <NotebookScene />
                <FirstCommitProbe />
            </BindLogic>
        )

        expect(firstCommit).not.toContain('not-found-notebook')
        expect(firstCommit).toContain('LemonSkeleton')
    })
})
