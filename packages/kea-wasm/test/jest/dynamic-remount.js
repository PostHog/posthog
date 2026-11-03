import { kea, useValues, useActions, getContext, resetContext } from '../../src'

import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

describe('dynamic remount', () => {
  beforeEach(() => {
    resetContext()
  })

  test('can change key/path of logic once it has been wrapped', () => {
    const { store } = getContext()
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'wrappy', key],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, props }) => ({
        name: [
          props.defaultName,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        upperCaseName: [
          () => [selectors.name],
          (name) => {
            return name.toUpperCase()
          },
        ],
      }),
    })

    function SampleComponent({ id, name, upperCaseName, actions: { updateName } }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="name">{name}</div>
          <div data-testid="upperCaseName">{upperCaseName}</div>
          <div data-testid="updateName" onClick={() => updateName('fred')}>
            updateName
          </div>
        </div>
      )
    }

    const ConnectedSampleComponent = logic(SampleComponent)

    const togglerLogic = kea({
      path: () => ['scenes', 'toggler'],
      actions: () => ({
        next: true,
      }),
      reducers: ({ actions }) => ({
        id: [
          12,
          {
            [actions.next]: (state) => state + 1,
          },
        ],
      }),
    })

    function TogglerComponent() {
      const { id } = useValues(togglerLogic)
      const { next } = useActions(togglerLogic)

      return (
        <div>
          <ConnectedSampleComponent id={id} defaultName="brad" />
          <button data-testid="next" onClick={next}>
            next
          </button>
        </div>
      )
    }

    render(<TogglerComponent />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('brad')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('BRAD')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: {
        wrappy: { 12: { name: 'brad' } },
        toggler: { id: 12 },
      },
    })

    fireEvent.click(screen.getByTestId('updateName'))

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('fred')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('FRED')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: {
        wrappy: { 12: { name: 'fred' } },
        toggler: { id: 12 },
      },
    })

    fireEvent.click(screen.getByTestId('next'))

    expect(screen.getByTestId('id')).toHaveTextContent('13')
    expect(screen.getByTestId('name')).toHaveTextContent('brad')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('BRAD')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: {
        wrappy: { 13: { name: 'brad' } },
        toggler: { id: 13 },
      },
    })
  })
})
