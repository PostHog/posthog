import { kea, resetContext, getContext } from '../../src'

import React from 'react'
import { render, screen, act } from '@testing-library/react'

describe('defaults', () => {
  beforeEach(() => {
    resetContext()
  })

  test('defaults from props for lazy', () => {
    function SampleComponent({ id, propsName, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="propsName">{propsName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const singletonLogic = kea({
      path: () => ['scenes', 'dynamic'],

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props, selectors }) => ({
        propsName: [
          props.defaultName,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.propsName],
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

    render(<ConnectedComponent id="12" defaultName="defaultName" />)

    expect(screen.getByTestId('propsName')).toHaveTextContent('defaultName')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Defaultname')

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { dynamic: { propsName: 'defaultName' } },
    })

    act(() => singletonLogic.actions.updateName('birb'))

    expect(store.getState()).toEqual({
      kea: {},
      scenes: { dynamic: { propsName: 'birb' } },
    })

    expect(screen.getByTestId('propsName')).toHaveTextContent('birb')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Birb')
  })

  test('defaults from selectors', () => {
    function SampleComponent({ id, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="connectedName">{connectedName}</div>
          <div data-testid="directName">{directName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const randomStore = kea({
      actions: () => ({
        updateStoredName: (storedName) => ({ storedName }),
      }),

      reducers: ({ actions }) => ({
        storedName: [
          'storedName',
          {
            [actions.updateStoredName]: (_, payload) => payload.storedName,
          },
        ],
      }),
    })

    const singletonLogic = kea({
      connect: {
        values: [randomStore, ['storedName']],
        actions: [randomStore, ['updateStoredName']],
      },

      path: () => ['scenes', 'dynamic'],

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props, selectors }) => ({
        connectedName: [
          selectors.storedName,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        // randomStore.selectors is not yet built, so we must delay calling it
        // with another selector or mount it before building this logic
        directName: [
          (state) => randomStore.selectors.storedName(state),
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.connectedName],
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

    render(<ConnectedComponent id="12" defaultName="defaultName" />)

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Storedname')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('storedName')
    expect(screen.getByTestId('directName')).toHaveTextContent('storedName')

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'storedName' } } },
      scenes: { dynamic: { connectedName: 'storedName', directName: 'storedName' } },
    })

    act(() => store.dispatch(singletonLogic.actionCreators.updateStoredName('birb')))

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'birb' } } },
      scenes: { dynamic: { connectedName: 'storedName', directName: 'storedName' } },
    })

    act(() => singletonLogic.actions.updateName('birb'))

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'birb' } } },
      scenes: { dynamic: { connectedName: 'birb', directName: 'birb' } },
    })

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Birb')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('birb')
    expect(screen.getByTestId('directName')).toHaveTextContent('birb')
  })

  test('defaults from input.defaults selector', () => {
    function SampleComponent({ id, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="connectedName">{connectedName}</div>
          <div data-testid="directName">{directName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const randomStore = kea({
      actions: () => ({
        updateStoredName: (storedName) => ({ storedName }),
      }),

      reducers: ({ actions }) => ({
        storedName: [
          'storedName',
          {
            [actions.updateStoredName]: (_, payload) => payload.storedName,
          },
        ],
      }),
    })

    randomStore.mount()

    const dynamicLogic = kea({
      connect: {
        values: [randomStore, ['storedName']],
        actions: [randomStore, ['updateStoredName']],
      },

      key: (props) => props.id,
      path: (key) => ['scenes', 'dynamic', key],

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      defaults:
        ({ selectors }) =>
        (state, props) => ({
          // using the selector syntax for the entire object
          connectedName: selectors.storedName(state), // gets a value
          directName: randomStore.selectors.storedName, // gets passed as a selector
        }),

      reducers: ({ actions }) => ({
        connectedName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        directName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.connectedName],
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

    const ConnectedComponent = dynamicLogic(SampleComponent)

    render(<ConnectedComponent id="12" defaultName="defaultName" />)

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Storedname')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('storedName')
    expect(screen.getByTestId('directName')).toHaveTextContent('storedName')

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { storedName: 'storedName' } } },
      scenes: { dynamic: { 12: { connectedName: 'storedName', directName: 'storedName' } } },
    })

    act(() => dynamicLogic({ id: 12 }).actions.updateStoredName('birb'))

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { storedName: 'birb' } } },
      scenes: { dynamic: { 12: { connectedName: 'storedName', directName: 'storedName' } } },
    })

    act(() => store.dispatch(dynamicLogic({ id: 12 }).actionCreators.updateName('birb')))

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { storedName: 'birb' } } },
      scenes: { dynamic: { 12: { connectedName: 'birb', directName: 'birb' } } },
    })

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Birb')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('birb')
    expect(screen.getByTestId('directName')).toHaveTextContent('birb')
  })

  test('defaults from props via input.defaults without selector', () => {
    function SampleComponent({ id, propsName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="propsName">{propsName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const lazyLogic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      defaults: ({ selectors, props }) => ({
        propsName: props.defaultName,
      }),

      reducers: ({ actions }) => ({
        propsName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.propsName],
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

    const ConnectedComponent = lazyLogic(SampleComponent)

    render(<ConnectedComponent id="12" defaultName="defaultName" />)

    expect(screen.getByTestId('propsName')).toHaveTextContent('defaultName')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Defaultname')

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { propsName: 'defaultName' } } },
    })

    act(() => lazyLogic.actions.updateName('birb'))

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { propsName: 'birb' } } },
    })

    expect(screen.getByTestId('propsName')).toHaveTextContent('birb')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Birb')
  })

  test('defaults from selectors in input.defaults without selector', () => {
    function SampleComponent({ id, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="connectedName">{connectedName}</div>
          <div data-testid="directName">{directName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const randomStore = kea({
      actions: () => ({
        updateStoredName: (storedName) => ({ storedName }),
      }),

      reducers: ({ actions }) => ({
        storedName: [
          'storedName',
          {
            [actions.updateStoredName]: (_, payload) => payload.storedName,
          },
        ],
      }),
    })

    const singletonLogic = kea({
      connect: {
        values: [randomStore, ['storedName']],
        actions: [randomStore, ['updateStoredName']],
      },

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      defaults: ({ selectors, props }) => ({
        // using the selector syntax for the entire object
        connectedName: selectors.storedName, // gets a value
        directName: 'george', // gets passed as a selector
      }),

      reducers: ({ actions }) => ({
        connectedName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        directName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.connectedName],
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

    render(<ConnectedComponent id="12" defaultName="defaultName" />)

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Storedname')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('storedName')
    expect(screen.getByTestId('directName')).toHaveTextContent('george')

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'storedName' }, 1: { connectedName: 'storedName', directName: 'george' } } },
    })

    act(() => singletonLogic.actions.updateStoredName('birb'))

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'birb' }, 1: { connectedName: 'storedName', directName: 'george' } } },
    })

    act(() => store.dispatch(singletonLogic.actionCreators.updateName('birb')))

    expect(store.getState()).toEqual({
      kea: { logic: { 2: { storedName: 'birb' }, 1: { connectedName: 'birb', directName: 'birb' } } },
    })

    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Birb')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('birb')
    expect(screen.getByTestId('directName')).toHaveTextContent('birb')
  })

  test('defaults from input.defaults as object', () => {
    function SampleComponent({ id, propsName, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="propsName">{propsName}</div>
          <div data-testid="connectedName">{connectedName}</div>
          <div data-testid="directName">{directName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const singletonLogic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      defaults: {
        propsName: 'defaultName',
        connectedName: 'storedName',
        directName: 'george',
      },

      reducers: ({ actions }) => ({
        propsName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        connectedName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        directName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.propsName],
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

    render(<ConnectedComponent />)

    expect(screen.getByTestId('propsName')).toHaveTextContent('defaultName')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Defaultname')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('storedName')
    expect(screen.getByTestId('directName')).toHaveTextContent('george')

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { propsName: 'defaultName', connectedName: 'storedName', directName: 'george' } } },
    })
  })

  test('defaults from selector that returns an object', () => {
    function SampleComponent({ id, propsName, connectedName, directName, capitalizedName }) {
      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="propsName">{propsName}</div>
          <div data-testid="connectedName">{connectedName}</div>
          <div data-testid="directName">{directName}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
        </div>
      )
    }

    const { store } = getContext()

    const randomStore = kea({
      actions: () => ({
        updateObject: (object) => ({ object }),
      }),

      reducers: ({ actions }) => ({
        object: [
          { propsName: 'henry', connectedName: 'george', directName: 'joe' },
          {
            [actions.updateObject]: (state, payload) => ({ ...state, ...payload.object }),
          },
        ],
      }),
    })

    const singletonLogic = kea({
      connect: {
        values: [randomStore, ['object']],
        actions: [randomStore, ['updateObject']],
      },

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      defaults: ({ selectors }) => selectors.object,

      reducers: ({ actions }) => ({
        propsName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        connectedName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
        directName: [
          '',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),

      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.propsName],
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

    render(<ConnectedComponent />)

    expect(screen.getByTestId('propsName')).toHaveTextContent('henry')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Henry')
    expect(screen.getByTestId('connectedName')).toHaveTextContent('george')
    expect(screen.getByTestId('directName')).toHaveTextContent('joe')

    expect(store.getState()).toEqual({
      kea: {
        logic: {
          1: { propsName: 'henry', connectedName: 'george', directName: 'joe' },
          2: { object: { propsName: 'henry', connectedName: 'george', directName: 'joe' } },
        },
      },
    })
  })
})
