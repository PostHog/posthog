import { kea, createStore, resetContext, getContext } from '../../src'
import React, { Component } from 'react'
import { render, screen } from '@testing-library/react'

class SampleComponent extends Component {
  render() {
    const { id, name, capitalizedName } = this.props
    const { updateName } = this.actions

    return (
      <div>
        <div data-testid="id">{id}</div>
        <div data-testid="name">{name}</div>
        <div data-testid="capitalizedName">{capitalizedName}</div>
        <div data-testid="updateName" onClick={updateName}>
          updateName
        </div>
      </div>
    )
  }
}

describe('store', () => {
  beforeEach(() => {
    resetContext({ createStore: false })
  })

  test('getStore can be initalized with a preloaded state for non-kea reducers', () => {
    const preloadedState = {
      kea: {},
      scenes: { something: { name: 'chirpy' } },
      routes: { someRoute: true },
    }
    const store = createStore({
      reducers: {
        routes: (state = {}, action) => state,
      },
      preloadedState: preloadedState,
    })
    expect(store.getState()).toEqual({
      kea: {},
      routes: { someRoute: true },
    })
  })

  test('getStore preloaded state will be immidiatly overiden by reducer default state', () => {
    // use defaults instead of initalizing kea reducers

    const preloadedState = {
      kea: {},
      scenes: { something: { name: 'chirpoo' } },
    }
    const store = createStore({
      preloadedState,
    })

    const singletonLogic = kea({
      path: () => ['scenes', 'something'],
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

    const ConnectedComponent = singletonLogic(SampleComponent)

    render(<ConnectedComponent id={12} />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { something: { name: 'chirpy' } },
    })
  })

  test('can use createStore on resetContext', () => {
    const context = resetContext({
      createStore: true,
    })

    expect(context).toBe(getContext())
    expect(context.store).toBeDefined()
    expect(Object.keys(context.store.getState()).sort()).toEqual(['kea'])

    const secondContext = resetContext({
      createStore: {
        paths: ['kea', 'scenes', 'parrots'],
      },
    })

    expect(secondContext).toBe(getContext())
    expect(secondContext.store).toBeDefined()
    expect(Object.keys(secondContext.store.getState()).sort()).toEqual(['kea', 'parrots', 'scenes'])
  })

  test('can create reducers with random paths', () => {
    const context = resetContext({
      createStore: {
        reducers: {
          router: () => 'router',
        },
      },
    })

    expect(Object.keys(context.store.getState()).sort()).toEqual(['kea', 'router'])

    const existingLogic = kea({
      path: () => ['parrots', 'nz', 'kea'],
      reducers: () => ({
        sheep: ['tasty'],
      }),
    })

    const nonExistingLogic = kea({
      path: () => ['birds', 'nz', 'kea'],
      reducers: () => ({
        sheep: ['tasty'],
      }),
    })

    existingLogic.mount()
    expect(context.store.getState().parrots.nz.kea.sheep).toBe('tasty')

    nonExistingLogic.mount()
    expect(context.store.getState().birds.nz.kea.sheep).toBe('tasty')

    expect(Object.keys(context.store.getState()).sort()).toEqual(['birds', 'kea', 'parrots', 'router'])
  })

  test('can not create reducers with random paths if restricted', () => {
    const context = resetContext({
      createStore: {
        paths: ['kea', 'scenes', 'parrots'],
        reducers: {
          router: () => 'router',
        },
      },
    })

    expect(Object.keys(context.store.getState()).sort()).toEqual(['kea', 'parrots', 'router', 'scenes'])

    const existingLogic = kea({
      path: () => ['parrots', 'nz', 'kea'],
      reducers: () => ({
        sheep: ['tasty'],
      }),
    })

    const nonExistingLogic = kea({
      path: () => ['birds', 'nz', 'kea'],
      reducers: () => ({
        sheep: ['tasty'],
      }),
    })

    existingLogic.mount()

    expect(context.store.getState().parrots.nz.kea.sheep).toBe('tasty')

    expect(() => {
      nonExistingLogic.mount()
    }).toThrow(`[KEA] Can not start reducer's path with "birds"! Please add it to the whitelist`)
  })
})
