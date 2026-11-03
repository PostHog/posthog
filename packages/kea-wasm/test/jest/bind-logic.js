import { kea, resetContext, getContext, useValues, BindLogic } from '../../src'
import React, { useState } from 'react'
import { render, screen } from '@testing-library/react'
import { act } from 'react-dom/test-utils'

describe('bind logic', () => {
  beforeEach(() => {
    resetContext()
  })

  test('multiple dynamic logic stores', () => {
    let setState
    const { store } = getContext()

    const allNames = [
      { id: 12, name: 'bla' },
      { id: 13, name: 'george' },
      { id: 15, name: 'michael' },
    ]

    const keyedLogic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'dynamic', key],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, props }) => ({
        name: [
          allNames.find((n) => n.id === props.id)?.name || props.defaultName || '',
          {
            updateName: (_, { name }) => name,
          },
        ],
      }),
    })

    function App() {
      const [state, _setState] = useState({ firstId: 12, secondId: 15 })
      setState = (stateUpdate) => act(() => _setState({ ...state, ...stateUpdate }))

      const { firstId, secondId } = state

      return (
        <div data-testid="app">
          <BindLogic logic={keyedLogic} props={{ id: firstId }}>
            <DynamicComponent __debugId={firstId} />
          </BindLogic>
          <BindLogic logic={keyedLogic} props={{ id: secondId }}>
            <DynamicComponent __debugId={secondId} />
          </BindLogic>
        </div>
      )
    }

    function DynamicComponent({ __debugId }) {
      const { name } = useValues(keyedLogic)
      return <div data-testid="name">{name}</div>
    }

    render(<App />)

    expect(screen.getAllByTestId('name').length).toEqual(2)

    const findText = () =>
      wrapper
        .find('.name')
        .map((node) => node.text())
        .join(',')

    const getStoreActions = () => Object.keys(store.getState().scenes?.dynamic || {}).map((nr) => parseInt(nr))

    expect(screen.getByTestId('app')).toHaveTextContent('blamichael')
    expect(getStoreActions()).toEqual([12, 15])

    const logic1 = keyedLogic({ id: 12 })
    const unmount1 = logic1.mount()

    expect(screen.getByTestId('app')).toHaveTextContent('blamichael')
    act(() => logic1.actions.updateName('haha'))
    expect(screen.getByTestId('app')).toHaveTextContent('hahamichael')
    expect(getStoreActions()).toEqual([12, 15])
    unmount1()

    const logic2 = keyedLogic({ id: 15 })
    const unmount2 = logic2.mount()
    act(() => logic2.actions.updateName('hoho'))
    expect(screen.getByTestId('app')).toHaveTextContent('hahahoho')
    expect(getStoreActions()).toEqual([12, 15])
    unmount2()

    setState({ firstId: 13 })

    expect(screen.getByTestId('app')).toHaveTextContent('georgehoho')

    expect(getStoreActions()).toEqual([13, 15])
  })
})
