import { kea, getContext, resetContext } from '../../src'

import React from 'react'
import { render, screen, act } from '@testing-library/react'

describe('connect', () => {
  beforeEach(() => {
    resetContext()
  })

  test('connect works as an object', () => {
    const { store } = getContext()
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: {
        values: [connectedLogic, ['description']],
      },

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

    const SampleComponent = ({ id, name, capitalizedName, description, actions: { updateName } }) => (
      <div>
        <div data-testid="id">{id}</div>
        <div data-testid="name">{name}</div>
        <div data-testid="capitalizedName">{capitalizedName}</div>
        <div data-testid="description">{description}</div>
        <div data-testid="updateName" onClick={updateName}>
          updateName
        </div>
      </div>
    )

    const ConnectedComponent = logic(SampleComponent)

    expect(store.getState()).toEqual({ kea: {} })

    render(<ConnectedComponent id={12} />)

    expect(store.getState()).toEqual({ kea: { logic: { 1: { name: 'chirpy' }, 2: { description: 'default' } } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('description')).toHaveTextContent('default')

    expect(store.getState()).toEqual({ kea: { logic: { 1: { name: 'chirpy' }, 2: { description: 'default' } } } })

    act(() => logic.actions.updateName('somename'))
    act(() => connectedLogic.actions.updateDescription('new description'))

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { name: 'somename' }, 2: { description: 'new description' } } },
    })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('description')).toHaveTextContent('new description')
  })

  test('connect works as a function', () => {
    const { store } = getContext()
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: () => ({
        values: [connectedLogic, ['description']],
      }),

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

    const SampleComponent = ({ id, name, capitalizedName, description, actions: { updateName } }) => (
      <div>
        <div data-testid="id">{id}</div>
        <div data-testid="name">{name}</div>
        <div data-testid="capitalizedName">{capitalizedName}</div>
        <div data-testid="description">{description}</div>
        <div data-testid="updateName" onClick={updateName}>
          updateName
        </div>
      </div>
    )

    const ConnectedComponent = logic(SampleComponent)

    expect(store.getState()).toEqual({ kea: {} })

    render(<ConnectedComponent id={12} />)

    expect(store.getState()).toEqual({ kea: { logic: { 1: { name: 'chirpy' }, 2: { description: 'default' } } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('description')).toHaveTextContent('default')

    expect(store.getState()).toEqual({ kea: { logic: { 1: { name: 'chirpy' }, 2: { description: 'default' } } } })

    act(() => store.dispatch(logic.actionCreators.updateName('somename')))
    act(() => store.dispatch(connectedLogic.actionCreators.updateDescription('new description')))

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { name: 'somename' }, 2: { description: 'new description' } } },
    })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('description')).toHaveTextContent('new description')
  })

  test('props cascade when connecting', () => {
    const { store } = getContext()

    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions, props }) => ({
        description: [
          props.defaultDescription || '',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: {
        values: [connectedLogic, ['description']],
      },

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props }) => ({
        name: [
          `chirpy-${props.id}`,
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

    const SampleComponent = ({ id, name, capitalizedName, description, actions: { updateName } }) => (
      <div>
        <div data-testid="id">{id}</div>
        <div data-testid="name">{name}</div>
        <div data-testid="capitalizedName">{capitalizedName}</div>
        <div data-testid="description">{description}</div>
        <div data-testid="updateName" onClick={updateName}>
          updateName
        </div>
      </div>
    )

    const ConnectedComponent = logic(SampleComponent)

    expect(store.getState()).toEqual({ kea: {} })

    render(<ConnectedComponent id={12} defaultDescription="this is a bird" />)

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { name: 'chirpy-12' }, 2: { description: 'this is a bird' } } },
    })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy-12')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy-12')
    expect(screen.getByTestId('description')).toHaveTextContent('this is a bird')

    act(() => {
      logic.actions.updateName('somename')
      connectedLogic.actions.updateDescription('new description')
    })

    expect(store.getState()).toEqual({
      kea: { logic: { 1: { name: 'somename' }, 2: { description: 'new description' } } },
    })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('description')).toHaveTextContent('new description')
  })

  test('can connect logic without values/actions', () => {
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions, props }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: {
        logic: [connectedLogic],
      },

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props }) => ({
        name: [
          `chirpy-${props.id}`,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
    })

    logic({ id: 12 }).mount()

    expect(logic.values.name).toEqual('chirpy-12')
    expect(connectedLogic.values.description).toEqual('default')
  })

  test('can connect logic via array', () => {
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions, props }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: [connectedLogic],

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props }) => ({
        name: [
          `chirpy-${props.id}`,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
    })

    logic({ id: 12 }).mount()

    expect(logic.values.name).toEqual('chirpy-12')
    expect(connectedLogic.values.description).toEqual('default')
  })

  test('can connect logic directly', () => {
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions, props }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: connectedLogic,

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props }) => ({
        name: [
          `chirpy-${props.id}`,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
    })

    logic({ id: 12 }).mount()

    expect(logic.values.name).toEqual('chirpy-12')
    expect(connectedLogic.values.description).toEqual('default')
  })

  test('can connect built logic directly', () => {
    const connectedLogic = kea({
      actions: () => ({
        updateDescription: (description) => ({ description }),
      }),

      reducers: ({ actions, props }) => ({
        description: [
          'default',
          {
            [actions.updateDescription]: (_, payload) => payload.description,
          },
        ],
      }),
    })

    const logic = kea({
      connect: () => connectedLogic(),

      actions: () => ({
        updateName: (name) => ({ name }),
      }),

      reducers: ({ actions, props }) => ({
        name: [
          `chirpy-${props.id}`,
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
    })

    logic({ id: 12 }).mount()

    expect(logic.values.name).toEqual('chirpy-12')
    expect(connectedLogic.values.description).toEqual('default')
  })

  describe('can connect in a loop', () => {
    const runTest = (buildTheLogic = true) => {
      let logic1
      let logic2

      logic1 = kea({
        connect: () => ({
          values: [buildTheLogic ? logic2() : logic2, ['value2 as connectValue2']],
          actions: [buildTheLogic ? logic2() : logic2, ['action2']],
          logic: [buildTheLogic ? logic2() : logic2],
        }),
        actions: { action1: true },
        reducers: { value1: ['string1', { action1: () => 'action1', action2: () => 'action2' }] },
        selectors: () => ({ value2: [() => [(state) => logic2.selectors.value2(state)], (value2) => value2] }),
        // selectors: () => ({ value2: [() => [logic2.selectors.value2], (value2) => value2] }),
      })

      logic2 = kea({
        connect: () => ({
          values: [buildTheLogic ? logic1() : logic1, ['value1 as connectValue1']],
          actions: [buildTheLogic ? logic1() : logic1, ['action1']],
          logic: [buildTheLogic ? logic1() : logic1],
        }),
        actions: { action2: true },
        reducers: { value2: ['string2', { action1: () => 'action1', action2: () => 'action2' }] },
        selectors: () => ({ value1: [() => [(state) => logic1.selectors.value1(state)], (value1) => value1] }),
        // selectors: () => ({ value1: [() => [logic1.selectors.value1], (value1) => value1] }),
      })

      let unmount
      expect(() => {
        unmount = logic1.mount()
      }).toThrow('[KEA] Circular build detected.')
    }

    test('built logic', () => runTest(true))
    test('logic wrapper', () => runTest(false))
  })
})
