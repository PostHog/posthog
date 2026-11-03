import { kea, resetContext, getContext } from '../../src'

import React from 'react'
import { render, screen, act } from '@testing-library/react'

describe('double render', () => {
  beforeEach(() => {
    resetContext()
  })

  test('does not double render with the same props', () => {
    const { store } = getContext()

    const logic = kea({
      path: () => ['scenes', 'lazy'],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions }) => ({
        name: [
          'chirpy',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        upperCaseName: [
          () => [selectors.capitalizedName],
          (capitalizedName) => {
            return capitalizedName.toUpperCase()
          },
        ],
        capitalizedName: [
          () => [selectors.name],
          (name) => {
            return name
              .trim()
              .split(' ')
              .map((k) => `${k.charAt(0).toUpperCase()}${k.slice(1).toLowerCase()}`)
              .join(' ')
          },
        ],
      }),
    })

    let countRendered = 0

    function SampleComponent({ id, name, capitalizedName, upperCaseName, actions: { updateName } }) {
      countRendered += 1

      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="name">{name}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
          <div data-testid="upperCaseName">{upperCaseName}</div>
          <div data-testid="updateName" onClick={updateName}>
            updateName
          </div>
        </div>
      )
    }

    const ConnectedComponent = logic(SampleComponent)

    expect(countRendered).toEqual(0)

    render(<ConnectedComponent id={12} />)

    expect(countRendered).toEqual(1)

    act(() => store.dispatch({ type: 'nothing', payload: {} }))
    expect(countRendered).toEqual(1)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('CHIRPY')

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { name: 'chirpy' } } })

    act(() => store.dispatch(logic.actionCreators.updateName('somename')))
    expect(countRendered).toEqual(2)

    act(() => logic.actions.updateName('somename'))
    expect(countRendered).toEqual(2)

    act(() => store.dispatch(logic.actionCreators.updateName('somename3')))
    expect(countRendered).toEqual(3)

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { name: 'somename3' } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename3')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename3')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME3')
  })
})
