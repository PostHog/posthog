import { kea, resetContext, getContext } from '../../src'

import React, { Component } from 'react'
import { render, screen, act } from '@testing-library/react'

class SampleComponent extends Component {
  render() {
    const { id, name, capitalizedName, upperCaseName } = this.props
    const { updateName } = this.actions

    return (
      <div data-testid={`sample-${id}`}>
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
}

class ActionComponent extends Component {
  render() {
    return (
      <div>
        <div data-testid="actions">{Object.keys(this.actions).sort().join(',')}</div>
        <div data-testid="props">{Object.keys(this.props).sort().join(',')}</div>
        <div data-testid="name">{this.props.name}</div>
      </div>
    )
  }
}
describe('logic component', () => {
  beforeEach(() => {
    resetContext()
  })

  test('singletons connect to react components', () => {
    const { store } = getContext()

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

    const ConnectedComponent = singletonLogic(SampleComponent)

    render(<ConnectedComponent id={12} />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('CHIRPY')

    expect(store.getState()).toEqual({ kea: {}, scenes: { something: { name: 'chirpy' } } })

    act(() => singletonLogic.actions.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { something: { name: 'somename' } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME')
  })

  test('dynamic connect to react components', () => {
    const { store } = getContext()

    const dynamicLogic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'something', key],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, key }) => ({
        name: [
          'chirpy',
          {
            [actions.updateName]: (state, payload) => payload.name + key,
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

    const ConnectedComponent = dynamicLogic(SampleComponent)

    render(<ConnectedComponent id={12} />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('CHIRPY')

    expect(store.getState()).toEqual({ kea: {}, scenes: { something: { 12: { name: 'chirpy' } } } })

    act(() => dynamicLogic({ id: 12 }).actions.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { something: { 12: { name: 'somename12' } } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename12')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename12')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME12')
  })

  test('connected props can be used as selectors', () => {
    const { store } = getContext()

    const firstLogic = kea({
      path: () => ['scenes', 'homepage', 'first'],
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
    })

    const secondLogic = kea({
      path: () => ['scenes', 'homepage', 'second'],
      connect: {
        values: [firstLogic, ['name']],
        actions: [firstLogic, ['updateName']],
      },
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

    const ConnectedComponent = secondLogic(SampleComponent)

    render(<ConnectedComponent id={12} />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('chirpy')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Chirpy')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('CHIRPY')

    expect(store.getState()).toEqual({ kea: {}, scenes: { homepage: { first: { name: 'chirpy' } } } })

    act(() => secondLogic.actions.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { homepage: { first: { name: 'somename' } } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('somename')
    expect(screen.getByTestId('capitalizedName')).toHaveTextContent('Somename')
    expect(screen.getByTestId('upperCaseName')).toHaveTextContent('SOMENAME')
  })

  test('doubly connected actions are merged', () => {
    const { store } = getContext()

    const firstLogic = kea({
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
    })

    const secondLogic = kea({
      actions: () => ({
        updateNameAgain: (name) => ({ name }),
      }),
    })

    const ConnectedComponent = firstLogic(secondLogic(ActionComponent))

    render(<ConnectedComponent />)

    expect(screen.getByTestId('props')).toHaveTextContent('actions,dispatch,name')
    expect(screen.getByTestId('actions')).toHaveTextContent('updateName,updateNameAgain')
  })

  test('no protypes needed', () => {
    const { store } = getContext()

    const firstLogic = kea({
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
    })

    const secondLogic = kea({
      actions: () => ({
        updateNameAgain: (name) => ({ name }),
      }),
    })

    const ConnectedComponent = firstLogic(secondLogic(ActionComponent))

    render(<ConnectedComponent />)

    expect(screen.getByTestId('props')).toHaveTextContent('actions,dispatch,name')
    expect(screen.getByTestId('actions')).toHaveTextContent('updateName,updateNameAgain')

    act(() => firstLogic.actions.updateName('somename'))

    expect(screen.getByTestId('name')).toHaveTextContent('somename')
  })

  test('can select with regular', () => {
    const { store } = resetContext({
      createStore: {
        reducers: {
          random: () => ({ some: 'value' }),
        },
      },
    })

    const logic = kea({
      path: () => ['scenes', 'kea', 'first'],

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
    })

    const connectedLogic = kea({
      connect: {
        values: [logic, ['name'], (state) => state.random, ['some']],
      },
    })

    function RegularSelectorTest({ name, some }) {
      return (
        <div data-testid="values">
          {name},{some}
        </div>
      )
    }

    const ConnectedComponent = connectedLogic(RegularSelectorTest)

    render(<ConnectedComponent />)

    expect(screen.getByTestId('values')).toHaveTextContent('chirpy,value')
  })

  test('dynamic reducer initial props', () => {
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
      <div>
        <div data-testid="id">{id}</div>
        <div data-testid="name">{name}</div>
      </div>
    )

    const ConnectedComponent = dynamicLogic(SampleComponent)

    render(<ConnectedComponent id={12} defaultName="bird" />)

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('bird')

    expect(store.getState()).toEqual({ kea: {}, scenes: { dynamic: { 12: { name: 'bird' } } } })

    act(() => store.dispatch(dynamicLogic({ id: 12 }).actionCreators.updateName('birb')))

    expect(store.getState()).toEqual({ kea: {}, scenes: { dynamic: { 12: { name: 'birb' } } } })

    expect(screen.getByTestId('id')).toHaveTextContent('12')
    expect(screen.getByTestId('name')).toHaveTextContent('birb')
  })
})
