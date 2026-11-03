import { kea, resetContext, getContext } from '../../src'

import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'

describe('nested unmount', () => {
  beforeEach(() => {
    resetContext()
  })

  test('updating state to remove logic from react unmounts neatly', () => {
    const { store } = getContext()

    // inner

    const innerLogic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, props, key }) => ({
        name: [
          'George',
          {
            [actions.updateName]: (_, payload) => payload.name,
          },
        ],
      }),
    })

    const InnerComponent = ({ name, actions: { updateName } }) => (
      <div>
        <div data-testid="name">{name}</div>
        <div data-testid="update-name"></div>
      </div>
    )

    const ConnectedInnerComponent = innerLogic(InnerComponent)

    // outer

    const outerLogic = kea({
      actions: () => ({
        showInner: true,
        hideInner: true,
      }),
      reducers: ({ actions, props, key }) => ({
        innerShown: [
          true,
          {
            [actions.showInner]: () => true,
            [actions.hideInner]: () => false,
          },
        ],
      }),
    })

    const OuterComponent = ({ innerShown, actions: { showInner, hideInner } }) => (
      <div>
        <div data-testid="inner-shown">{innerShown ? 'true' : 'false'}</div>
        <div data-testid="inner-hide">
          <button data-testid="inner-hide-button" onClick={hideInner}>
            hide
          </button>
        </div>
        <div data-testid="inner-show">
          <button data-testid="inner-show-button" onClick={showInner}>
            show
          </button>
        </div>
        <div data-testid="inner-div">{innerShown ? <ConnectedInnerComponent /> : null}</div>
      </div>
    )

    const ConnectedOuterComponent = outerLogic(OuterComponent)

    // start

    render(<ConnectedOuterComponent />)

    expect(screen.getByTestId('inner-shown')).toHaveTextContent('true')
    expect(screen.getByTestId('name')).toHaveTextContent('George')

    fireEvent.click(screen.getByTestId('inner-hide-button'))

    expect(screen.getByTestId('inner-shown')).toHaveTextContent('false')
    expect(screen.queryByTestId('name')).toEqual(null)
  })

  test('swapping out connected logic gives the right state', () => {
    const { store } = getContext()

    const outerLogic = kea({
      actions: () => ({
        showEdit: true,
        hideEdit: true,
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions, props, key }) => ({
        editShown: [
          false,
          {
            [actions.showEdit]: () => true,
            [actions.hideEdit]: () => false,
          },
        ],
        name: [
          'Bob',
          {
            [actions.updateName]: (_, payload) => payload.name,
          },
        ],
      }),
    })

    const editLogic = kea({
      connect: {
        values: [outerLogic, ['name']],
        actions: [outerLogic, ['updateName', 'hideEdit']],
      },
    })

    const EditComponent = ({ name, actions: { updateName, hideEdit } }) => (
      <div>
        <div data-testid="name">{name}</div>
        <button
          data-testid="save-and-close"
          onClick={() => {
            updateName('George')
            hideEdit()
          }}
        >
          hide
        </button>
      </div>
    )

    const ConnectedEditComponent = editLogic(EditComponent)

    const showLogic = kea({
      connect: {
        values: [outerLogic, ['name']],
      },
    })

    const ShowComponent = ({ name }) => (
      <div>
        <div data-testid="name">{name}</div>
      </div>
    )

    const ConnectedShowComponent = showLogic(ShowComponent)

    const OuterComponent = ({ editShown, actions: { showEdit } }) => (
      <div>
        <div data-testid="edit-shown">{editShown ? 'true' : 'false'}</div>
        <div data-testid="edit-show">
          <button data-testid="edit-show-button" onClick={showEdit}>
            show
          </button>
        </div>
        <div data-testid="edit-div">{editShown ? <ConnectedEditComponent /> : <ConnectedShowComponent />}</div>
      </div>
    )

    const ConnectedOuterComponent = outerLogic(OuterComponent)

    // start

    render(<ConnectedOuterComponent />)

    expect(screen.getByTestId('edit-shown')).toHaveTextContent('false')
    expect(screen.getByTestId('name')).toHaveTextContent('Bob')

    fireEvent.click(screen.getByTestId('edit-show-button'))

    expect(screen.getByTestId('edit-shown')).toHaveTextContent('true')
    expect(screen.getByTestId('name')).toHaveTextContent('Bob')

    fireEvent.click(screen.getByTestId('save-and-close'))

    expect(screen.getByTestId('edit-shown')).toHaveTextContent('false')
    expect(screen.getByTestId('name')).toHaveTextContent('George')
  })

  test('it also works with dynamic logic (with reducers)', () => {
    const { store } = getContext()

    const containerLogic = kea({
      path: () => ['scenes', 'container'],

      actions: () => ({
        increment: true,
        removeElementById: (id) => ({ id }),
        addElement: (element) => ({ element }),
        updateAllNames: (name) => ({ name }),
      }),

      reducers: ({ actions }) => ({
        elements: [
          {},
          {
            [actions.addElement]: (state, payload) => ({ ...state, [payload.element.id]: payload.element }),
            [actions.updateAllNames]: (state, payload) => {
              let newState = {}
              Object.keys(state).forEach((key) => {
                newState[key] = { ...state[key], name: payload.name }
              })
              return newState
            },
          },
        ],
        deletedElements: [
          {},
          {
            [actions.removeElementById]: (state, payload) => ({ ...state, [payload.id]: true }),
          },
        ],
        counter: [
          0,
          {
            [actions.increment]: (state) => state + 1,
          },
        ],
      }),
    })

    const elementLogic = kea({
      connect: {
        values: [containerLogic, ['elements']],
        actions: [containerLogic, ['removeElementById', 'updateAllNames', 'increment']],
      },

      key: (props) => props.id,
      path: (key) => ['scenes', 'element', key],

      // this is the only line that is different in the 2 tests
      reducers: () => ({}),

      selectors: ({ selectors }) => ({
        element: [() => [selectors.elements, (_, props) => props.id], (elements, id) => elements[id]],
      }),
    })

    const Element = elementLogic(
      ({ id, element: { name }, actions: { removeElementById, updateAllNames, increment } }) => (
        <li id={`element-${id}`}>
          <span data-testid="id">{id}</span>
          <span data-testid={`name-${id}`}>{name}</span>
          <button
            data-testid={`remove-and-rename-all-${id}`}
            onClick={() => {
              removeElementById(id)
              updateAllNames('new')
              increment()
            }}
          >
            remove
          </button>
        </li>
      ),
    )

    const ElementList = containerLogic(
      ({ counter, elements, deletedElements, actions: { increment, removeElementById, addElement } }) => (
        <div>
          <div>
            <button
              data-testid="add"
              onClick={() => {
                sampleElements.forEach((element) => {
                  addElement(element)
                })
                increment()
              }}
            >
              add
            </button>
            <button data-testid="increment" onClick={increment}>
              {counter}
            </button>
          </div>
          <ul>
            {Object.values(elements).map(({ id }) => (!deletedElements[id] ? <Element key={id} id={id} /> : null))}
          </ul>
        </div>
      ),
    )

    const sampleElements = [
      { id: '1', name: 'first' },
      { id: '2', name: 'second' },
      { id: '3', name: 'third' },
      { id: '4', name: 'fourth' },
      { id: '5', name: 'fifth' },
    ]

    render(<ElementList />)

    expect(screen.queryByTestId('name')).toEqual(null)
    expect(screen.getByTestId('increment')).toHaveTextContent('0')

    // click to add elements
    fireEvent.click(screen.getByTestId('add'))

    expect(screen.queryAllByTestId('id').length).toEqual(5)
    expect(screen.getByTestId('name-1')).toHaveTextContent('first')
    expect(screen.getByTestId('name-2')).toHaveTextContent('second')
    expect(screen.getByTestId('name-3')).toHaveTextContent('third')
    expect(screen.getByTestId('name-4')).toHaveTextContent('fourth')
    expect(screen.getByTestId('name-5')).toHaveTextContent('fifth')
    expect(screen.getByTestId('increment')).toHaveTextContent('1')

    // click to remove #2 and change the name of all to 'new
    fireEvent.click(screen.getByTestId('remove-and-rename-all-2'))

    expect(screen.queryAllByTestId('id').length).toEqual(4)
    expect(screen.getByTestId('name-1')).toHaveTextContent('new')
    expect(screen.getByTestId('name-3')).toHaveTextContent('new')
    expect(screen.getByTestId('name-4')).toHaveTextContent('new')
    expect(screen.getByTestId('name-5')).toHaveTextContent('new')
    expect(screen.getByTestId('increment')).toHaveTextContent('2')

    // increment to refresh the page
    fireEvent.click(screen.getByTestId('increment'))

    expect(screen.getByTestId('increment')).toHaveTextContent('3')
    expect(screen.queryAllByTestId('id').length).toEqual(4)
    expect(screen.getByTestId('name-1')).toHaveTextContent('new')
    expect(screen.getByTestId('name-3')).toHaveTextContent('new')
    expect(screen.getByTestId('name-4')).toHaveTextContent('new')
    expect(screen.getByTestId('name-5')).toHaveTextContent('new')
  })

  test('it also works with dynamic logic (without reducers)', () => {
    const { store } = getContext()

    const containerLogic = kea({
      path: () => ['scenes', 'container'],

      actions: () => ({
        increment: true,
        removeElementById: (id) => ({ id }),
        addElement: (element) => ({ element }),
        updateAllNames: (name) => ({ name }),
      }),

      reducers: ({ actions }) => ({
        elements: [
          {},
          {
            [actions.addElement]: (state, payload) => ({ ...state, [payload.element.id]: payload.element }),
            [actions.updateAllNames]: (state, payload) => {
              let newState = {}
              Object.keys(state).forEach((key) => {
                newState[key] = { ...state[key], name: payload.name }
              })
              return newState
            },
          },
        ],
        deletedElements: [
          {},
          {
            [actions.removeElementById]: (state, payload) => {
              return { ...state, [payload.id]: true }
            },
          },
        ],
        counter: [
          0,
          {
            [actions.increment]: (state) => state + 1,
          },
        ],
      }),
    })

    const elementLogic = kea({
      connect: {
        values: [containerLogic, ['elements']],
        actions: [containerLogic, ['removeElementById', 'updateAllNames', 'increment']],
      },

      key: (props) => props.id,
      path: (key) => ['scenes', 'element', key],

      // this is the only line that is different in the 2 tests
      // reducers: () => ({}),

      selectors: ({ selectors }) => ({
        element: [() => [selectors.elements, (_, props) => props.id], (elements, id) => elements[id]],
      }),
    })

    const Element = elementLogic(
      ({ id, element: { name }, actions: { removeElementById, updateAllNames, increment } }) => (
        <li id={`element-${id}`}>
          <span data-testid="id">{id}</span>
          <span data-testid={`name-${id}`}>{name}</span>
          <button
            data-testid={`remove-and-rename-all-${id}`}
            onClick={() => {
              // with or without batch, there's no difference
              removeElementById(id)
              updateAllNames('new')
              increment()
            }}
          >
            remove
          </button>
        </li>
      ),
    )

    const ElementList = containerLogic(({ counter, elements, deletedElements, actions: { increment, addElement } }) => (
      <div>
        <div>
          <button
            data-testid="add"
            onClick={() => {
              sampleElements.forEach((element) => {
                addElement(element)
              })
              increment()
            }}
          >
            add
          </button>
          <button data-testid="increment" onClick={increment}>
            {counter}
          </button>
        </div>
        <ul>{Object.values(elements).map(({ id }) => (!deletedElements[id] ? <Element key={id} id={id} /> : null))}</ul>
      </div>
    ))

    const sampleElements = [
      { id: '1', name: 'first' },
      { id: '2', name: 'second' },
      { id: '3', name: 'third' },
      { id: '4', name: 'fourth' },
      { id: '5', name: 'fifth' },
    ]

    render(<ElementList />)

    expect(screen.queryByTestId('id')).toEqual(null)
    expect(screen.getByTestId('increment')).toHaveTextContent('0')

    // click to add elements
    fireEvent.click(screen.getByTestId('add'))

    expect(screen.queryAllByTestId('id').length).toEqual(5)
    expect(screen.getByTestId('name-1')).toHaveTextContent('first')
    expect(screen.getByTestId('name-2')).toHaveTextContent('second')
    expect(screen.getByTestId('name-3')).toHaveTextContent('third')
    expect(screen.getByTestId('name-4')).toHaveTextContent('fourth')
    expect(screen.getByTestId('name-5')).toHaveTextContent('fifth')
    expect(screen.getByTestId('increment')).toHaveTextContent('1')

    // click to remove #2 and change the name of all to 'new'
    fireEvent.click(screen.getByTestId('remove-and-rename-all-2'))

    expect(screen.getByTestId('increment')).toHaveTextContent('2')
    expect(screen.getAllByTestId('id').length).toEqual(4)
    expect(screen.getByTestId('name-1')).toHaveTextContent('new')
    expect(screen.getByTestId('name-3')).toHaveTextContent('new')
    expect(screen.getByTestId('name-4')).toHaveTextContent('new')
    expect(screen.getByTestId('name-5')).toHaveTextContent('new')

    // increment to refresh the page
    fireEvent.click(screen.getByTestId('increment'))

    expect(screen.getByTestId('increment')).toHaveTextContent('3')
    expect(screen.getAllByTestId('id').length).toEqual(4)
    expect(screen.getByTestId('name-1')).toHaveTextContent('new')
    expect(screen.getByTestId('name-3')).toHaveTextContent('new')
    expect(screen.getByTestId('name-4')).toHaveTextContent('new')
    expect(screen.getByTestId('name-5')).toHaveTextContent('new')
  })
})
