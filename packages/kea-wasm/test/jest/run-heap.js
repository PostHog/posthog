import { getContext, resetContext, kea, useValues } from '../../src'
import React from 'react'
import { render, screen, act } from '@testing-library/react'

describe('run heap', () => {
  beforeEach(() => {
    resetContext()
  })

  test('run heap works with actions - build is not autoconnected via react', () => {
    const rootLogic = kea({
      path: () => ['scenes', 'root'],
      actions: () => ({
        loadScene: (scene) => ({ scene }),
        setScene: (scene) => ({ scene }),
      }),
      reducers: () => ({ scene: ['home', { setScene: (_, { scene }) => scene }] }),

      listeners: ({ actions }) => ({
        loadScene: ({ scene }) => {
          actions.setScene(scene)
        },
      }),
    })

    const dashLogic = kea({
      path: () => ['scenes', 'dash'],
      reducers: () => ({ dashValue: ['present'] }),
    })

    function DashComponent() {
      const { dashValue } = useValues(dashLogic())
      return <div data-testid="dashboard">{dashValue}</div>
    }

    function HomeComponent() {
      return <div data-testid="homepage">On Home</div>
    }

    function RootComponent() {
      const { scene } = useValues(rootLogic)
      return (
        <div>
          <div data-testid="scene">{scene}</div>
          {scene === 'home' ? <HomeComponent /> : null}😇
          {scene === 'dash' ? <DashComponent /> : null}
        </div>
      )
    }

    render(<RootComponent />)

    expect(screen.getByTestId('scene')).toHaveTextContent('home')
    expect(screen.getByTestId('homepage')).toHaveTextContent('On Home')
    expect(screen.queryByTestId('dashboard')).toEqual(null)

    expect(getContext().mount.counter).toEqual({ 'scenes.root': 1 })

    act(() => rootLogic.actions.loadScene('dash'))

    expect(getContext().mount.counter).toEqual({ 'scenes.dash': 1, 'scenes.root': 1 })
  })
})
