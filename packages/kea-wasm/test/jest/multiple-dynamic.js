import { kea, resetContext, getContext } from '../../src'

import React from 'react'
import { render, screen, act } from '@testing-library/react'

describe('multiple dynamic', () => {
  beforeEach(() => {
    resetContext()
  })

  test('multiple dynamic logic stores', () => {
    const { store } = getContext()

    const dynamicLogic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'dynamic', key],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, props, key }) => ({
        name: [
          props.defaultName,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
    })

    const SampleComponent = ({ id, name }) => (
      <div {...{ 'data-testid': `sample-${id}` }}>
        <h1>{id}</h1>
        <p>{name}</p>
      </div>
    )

    const ConnectedComponent = dynamicLogic(SampleComponent)

    const allNames = [
      { id: 12, name: 'bla' },
      { id: 13, name: 'george' },
      { id: 15, name: 'michael' },
    ]

    render(
      <>
        {allNames.map((name) => (
          <ConnectedComponent key={name.id} id={name.id} defaultName={name.name} />
        ))}
      </>,
    )
    expect(screen.getAllByRole('heading')).toHaveLength(3)

    expect(screen.getByTestId('sample-12')).toHaveTextContent('12bla')
    expect(screen.getByTestId('sample-13')).toHaveTextContent('13george')
    expect(screen.getByTestId('sample-15')).toHaveTextContent('15michael')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { dynamic: { 12: { name: 'bla' }, 13: { name: 'george' }, 15: { name: 'michael' } } },
    })

    act(() => dynamicLogic.build({ id: 12 }).actions.updateName('birb'))

    expect(screen.getByTestId('sample-12')).toHaveTextContent('12birb')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { dynamic: { 12: { name: 'birb' }, 13: { name: 'george' }, 15: { name: 'michael' } } },
    })
  })
})
