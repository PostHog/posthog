import { kea, props, resetContext, propsChanged, events, actions, listeners, shallowCompare } from '../../src'

describe('async actions', () => {
  beforeEach(() => {
    resetContext()
  })

  test('can wait for async actions', async () => {
    let listenerFinished = false
    let dispatchId = null

    const logic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      listeners: ({ actions, props }) => ({
        updateName: async (payload, breakpoint, action) => {
          await breakpoint(100)
          dispatchId = action.dispatchId
          listenerFinished = true
          return 'from1'
        },
      }),
    })

    logic.mount()
    const response = await logic.asyncActions.updateName('name')
    expect(response).toEqual('from1')
    expect(listenerFinished).toEqual(true)
    expect(dispatchId).toEqual(expect.any(String))
  })

  test('can wait for async actions with multiple logics', async () => {
    let listenersFinished = 0
    const dispatchIds = []

    const firstLogic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      listeners: () => ({
        updateName: async (payload, breakpoint, action) => {
          await breakpoint(100)
          listenersFinished += 1
          dispatchIds.push(action.dispatchId)
          return 'from1'
        },
      }),
    })
    const otherLogic = kea({
      connect: { actions: [firstLogic, ['updateName']] },
      listeners: ({ actions }) => ({
        updateName: async (payload, breakpoint, action) => {
          await breakpoint(200)
          listenersFinished += 1
          dispatchIds.push(action.dispatchId)
          return 'from2'
        },
      }),
    })

    firstLogic.mount()
    otherLogic.mount()
    const response = await firstLogic.asyncActions.updateName('name')
    expect(response).toEqual('from1')
    expect(listenersFinished).toEqual(2)
    expect(dispatchIds).toEqual([expect.any(String), expect.any(String)])
  })

  test('breakpoints', async () => {
    const finished = []
    let i = 0

    const logic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      listeners: () => ({
        updateName: async (payload, breakpoint, action) => {
          i++
          await breakpoint(100)
          finished.push(action.dispatchId)
          return `hello-${i}`
        },
      }),
    })

    logic.mount()
    const firstPromise = logic.asyncActions.updateName('name')
    const secondPromise = logic.asyncActions.updateName('name')

    // breakpoints cause us to wait until it finally resolves
    const val1 = await firstPromise
    expect(finished).toEqual([expect.any(String)])
    const val2 = await secondPromise
    expect(finished).toEqual([expect.any(String)])
    expect(val1).toEqual('hello-2')
    expect(val2).toEqual('hello-2')
  })

  test('respects disableAsyncActions', async () => {
    let listenerFinished = false
    let dispatchId = null

    resetContext({ disableAsyncActions: true })

    const logic = kea({
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      listeners: ({ actions, props }) => ({
        updateName: async (payload, breakpoint, action) => {
          dispatchId = action.dispatchId
          listenerFinished = true
        },
      }),
    })

    logic.mount()
    logic.actions.updateName('name')
    expect(logic.asyncActions).toEqual({})
    expect(logic.actionCreators.updateName('name').dispatchId).toBeUndefined()
  })
})
