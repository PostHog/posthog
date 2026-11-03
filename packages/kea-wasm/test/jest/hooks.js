import {
  kea,
  useValues,
  useAllValues,
  useActions,
  getContext,
  resetContext,
  path,
  actions,
  reducers,
  afterMount,
  useMountedLogic,
} from '../../src'

import React, { useEffect } from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { batchChanges } from '../../src/react/hooks'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

describe('hooks', () => {
  beforeEach(() => {
    resetContext()
  })

  test('useValues and useActions hooks works', () => {
    const { store } = getContext()
    const logic = kea({
      path: () => ['scenes', 'hooky'],
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

    function SampleComponent({ id }) {
      const { name, capitalizedName, upperCaseName } = useValues(logic)
      const { updateName } = useActions(logic)

      countRendered += 1

      return (
        <div>
          <div data-testid="id">{id}</div>
          <div data-testid="name">{name}</div>
          <div data-testid="capitalizedName">{capitalizedName}</div>
          <div data-testid="upperCaseName">{upperCaseName}</div>
          <div data-testid="updateName" onClick={() => updateName('bob')}>
            updateName
          </div>
        </div>
      )
    }

    expect(countRendered).toEqual(0)

    render(<SampleComponent id={12} />)

    expect(countRendered).toEqual(1)

    act(() => store.dispatch({ type: 'nothing', payload: {} }))

    expect(countRendered).toEqual(1)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('CHIRPY')

    expect(store.getState()).toEqual({ kea: {}, scenes: { hooky: { name: 'chirpy' } } })

    act(() => logic.actions.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { hooky: { name: 'somename' } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME')

    expect(countRendered).toEqual(2)
    logic.actions.updateName('somename')
    expect(countRendered).toEqual(2)

    act(() => logic.actions.updateName('somename3'))

    expect(countRendered).toEqual(3)

    expect(store.getState()).toEqual({ kea: {}, scenes: { hooky: { name: 'somename3' } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename3')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename3')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME3')

    fireEvent.click(screen.getByTestId('updateName'))

    expect(countRendered).toEqual(4)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('bob')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Bob')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('BOB')
  })

  test('useValues and useActions hooks accept logic built with props', () => {
    const { store } = getContext()
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'hooky', key],
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

    function SampleComponent({ id }) {
      const innerLogic = logic({ id, defaultName: 'brad' })

      const { name, upperCaseName } = useValues(innerLogic)
      const { updateName } = useActions(innerLogic)

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

    render(<SampleComponent id={12} />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('brad')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('BRAD')

    expect(store.getState()).toEqual({ kea: {}, scenes: { hooky: { 12: { name: 'brad' } } } })

    fireEvent.click(screen.getByTestId('updateName'))

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('fred')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('FRED')

    expect(store.getState()).toEqual({ kea: {}, scenes: { hooky: { 12: { name: 'fred' } } } })
  })

  test('can change key/path of logic once it has been accessed in a hook', () => {
    const { store } = getContext()
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'hooky', key],
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

    function SampleComponent({ id }) {
      const innerLogic = logic({ id, defaultName: 'brad' })

      const { name, upperCaseName } = useValues(innerLogic)
      const { updateName } = useActions(innerLogic)

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
          <SampleComponent id={id} />
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
        hooky: { 12: { name: 'brad' } },
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
        hooky: { 12: { name: 'fred' } },
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
        hooky: { 13: { name: 'brad' } },
        toggler: { id: 13 },
      },
    })
  })

  test('can get all props with useAllValuess', () => {
    const { store } = getContext()
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'hooky', key],
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

    function SampleComponent({ id }) {
      const innerLogic = logic({ id, defaultName: 'brad' })

      const allProps = useAllValues(innerLogic)

      const { name, upperCaseName } = allProps

      // extract the props a second time and expect nothing to break because of this
      if (id === 12) {
        const { name, upperCaseName } = allProps
        let a = name + upperCaseName
      }

      const { updateName } = useActions(innerLogic)

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
          <SampleComponent id={id} />
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
        hooky: { 12: { name: 'brad' } },
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
        hooky: { 12: { name: 'fred' } },
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
        hooky: { 13: { name: 'brad' } },
        toggler: { id: 13 },
      },
    })
  })

  test('will not crash hen running action after unmount', () => {
    const { store } = getContext()
    const logic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
    })

    function SampleComponent({ id }) {
      const { updateName } = useActions(logic)

      useEffect(() => {
        return () => updateName('yes')
      }, [])

      return <div />
    }

    render(<SampleComponent />)

    expect(() => {}).not.toThrow()
  })

  test('make sure the order of subscriptions does not matter', () => {
    const dashLogic = kea([
      path(['dashLogic']),
      actions({ doit: true }),
      reducers({ done: [false, { doit: () => true }] }),
    ])
    const otherLogic = kea([
      path(['otherLogic']),
      afterMount(() => {
        dashLogic.actions.doit()
      }),
    ])
    function Other() {
      const { done } = useValues(dashLogic)
      useMountedLogic(otherLogic)
      return <div data-testid="other">{done ? 'done' : 'doing'}</div>
    }
    function RenderTest() {
      const { done } = useValues(dashLogic)
      return (
        <>
          <div data-testid="scene">{done ? 'done' : 'doing'}</div>
          <Other />
        </>
      )
    }

    const { unmount } = render(<RenderTest />)

    expect(screen.getByTestId('other')).toHaveTextContent('done')
    expect(screen.getByTestId('scene')).toHaveTextContent('done')

    unmount()
  })

  it('batchChanges works as expected', async () => {
    resetContext({
      createStore: {
        middleware: [
          ({ dispatch, getState }) =>
            (next) =>
            (action) => {
              log.push({ type: `redux action ${action.type}`, path: action.payload?.path })
              next(action)
            },
        ],
      },
    })
    let log = []
    const dashLogic = kea([
      path(['dashLogic']),
      actions({ doit: true }),
      reducers({ done: [false, { doit: () => true }] }),
    ])
    const bashLogic = kea([
      path(['bashLogic']),
      actions({ doit: true }),
      reducers({ done: [false, { doit: () => true }] }),
    ])

    const { store } = getContext()
    store.subscribe(() => {
      log.push({ type: 'in redux listener', state: store.getState() })
    })

    log.push({ type: 'pre dashLogic mount' })
    dashLogic.mount()
    log.push({ type: 'post dashLogic mount' })

    log.push({ type: 'pre paused bashLogic mount' })
    batchChanges(() => {
      bashLogic.mount()
    })
    log.push({ type: 'post paused bashLogic mount' })
    log.push({ type: 'starting await' })

    await delay(0)

    log.push({ type: 'after await setTimeout(0)' })

    expect(log).toEqual([
      { type: 'pre dashLogic mount' },
      { type: 'redux action @KEA/ATTACH_REDUCER', path: ['dashLogic'] },
      { type: 'in redux listener', state: { kea: {}, dashLogic: { done: false } } },
      { type: 'post dashLogic mount' },
      { type: 'pre paused bashLogic mount' },
      { type: 'redux action @KEA/ATTACH_REDUCER', path: ['bashLogic'] },
      { type: 'post paused bashLogic mount' },
      { type: 'starting await' },
      { type: 'redux action @KEA/FLUSH', path: undefined },
      {
        type: 'in redux listener',
        state: { bashLogic: { done: false }, dashLogic: { done: false }, kea: {} },
      },
      { type: 'after await setTimeout(0)' },
    ])
    expect(1).toBe(1)
  })
})
