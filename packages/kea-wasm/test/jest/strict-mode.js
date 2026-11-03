import { getContext, reducers, resetContext, useMountedLogic, kea, path } from '../../src'
import React, { useEffect, useLayoutEffect } from 'react'
import { render } from '@testing-library/react'

// React.StrictMode is broken. Kea mounts its own logic *in the body of the component* -- yes, boohoo, I know --
// and that causes it to never unmount logic if React then renders it twice. This file documents the broken behaviour.
describe('strict mode', () => {
  beforeEach(() => {
    resetContext()
  })

  test('document broken behaviour', () => {
    let array = []
    const cl = (str) => array.push([str, getContext().mount.counter['scenes.dash']])

    const dashLogic = kea([path(['scenes', 'dash']), reducers({ dashValue: ['present'] })])

    function RenderTest() {
      cl('rendering')
      useEffect(() => {
        cl('useEffect')
        return () => {
          cl('useEffectReturn')
        }
      }, [])
      useLayoutEffect(() => {
        cl('useLayoutEffect')
        return () => {
          cl('useLayoutEffectReturn')
        }
      }, [])

      useMountedLogic(dashLogic)

      return <div />
    }

    const { unmount } = render(
      <React.StrictMode>
        <RenderTest />
      </React.StrictMode>,
    )
    cl('MID')
    unmount()
    cl('END')

    // TODO: This is documented, but wrong. Ideally we want to support StrictMode and not double-mount, but :shrug:
    expect(array).toEqual([
      ['rendering', undefined],
      ['rendering', 1], // the untracked "mount" is added here
      ['useLayoutEffect', 2],
      ['useEffect', 2],
      ['useLayoutEffectReturn', 2],
      ['useEffectReturn', 2],
      ['useLayoutEffect', 1],
      ['useEffect', 1],
      ['MID', 2],
      ['useLayoutEffectReturn', 2],
      ['useEffectReturn', 2],
      ['END', 1], // it should end with 0
    ])
  })
})
