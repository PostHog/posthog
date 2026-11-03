import { kea, resetContext, isBreakpoint, getPluginContext, listeners, actions } from '../../src'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

describe('listeners', () => {
  beforeEach(() => {
    resetContext()
  })

  test('listeners work', () => {
    let listenerRan = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'first'],
      actions: {
        updateName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'chirpy',
          {
            updateName: (state, payload) => payload.name,
          },
        ],
      },
      listeners: {
        updateName: () => {
          listenerRan = true
        },
      },
    })

    firstLogic.mount()

    expect(firstLogic._isKea).toBe(true)
    expect(Object.keys(firstLogic.actions)).toEqual(['updateName'])
    expect(Object.keys(firstLogic.selectors).sort()).toEqual(['name'])

    firstLogic.actions.updateName('derpy')
    expect(firstLogic.values.name).toBe('derpy')

    expect(listenerRan).toBe(true)
  })

  test('listeners work with local action keys', () => {
    let listenerRan = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'first'],
      actions: {
        updateName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'chirpy',
          {
            updateName: (state, payload) => payload.name,
          },
        ],
      },
      listeners: {
        updateName: () => {
          listenerRan = true
        },
      },
    })

    firstLogic.mount()

    firstLogic.actions.updateName('derpy')
    expect(firstLogic.values.name).toBe('derpy')

    expect(listenerRan).toBe(true)
  })

  test('sharedListeners work', () => {
    let listenerRan = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'test'],
      actions: {
        updateName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'chirpy',
          {
            updateName: (state, payload) => payload.name,
          },
        ],
      },
      listeners: ({ sharedListeners }) => ({
        updateName: sharedListeners.doUpdateName,
      }),
      sharedListeners: {
        doUpdateName() {
          listenerRan = true
        },
      },
    })

    firstLogic.mount()

    firstLogic.actions.updateName('derpy')
    expect(firstLogic.values.name).toBe('derpy')

    expect(listenerRan).toBe(true)
  })

  test('many listeners for one action', () => {
    let listenerRan1 = false
    let listenerRan2 = false
    let listenerRan3 = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'test'],
      actions: {
        updateName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'chirpy',
          {
            updateName: (state, payload) => payload.name,
          },
        ],
      },
      listeners: ({ sharedListeners }) => ({
        updateName: [
          sharedListeners.doUpdateName,
          sharedListeners.otherWorker,
          function () {
            listenerRan3 = true
          },
        ],
      }),
      sharedListeners: () => ({
        doUpdateName() {
          listenerRan1 = true
        },
        otherWorker() {
          listenerRan2 = true
        },
      }),
    })

    firstLogic.mount()

    firstLogic.actions.updateName('derpy')
    expect(firstLogic.values.name).toBe('derpy')

    expect(listenerRan1).toBe(true)
    expect(listenerRan2).toBe(true)
    expect(listenerRan3).toBe(true)
  })

  test('extend works', () => {
    let listenerRan1 = false
    let listenerRan2 = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'test'],
      actions: {
        updateName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'chirpy',
          {
            updateName: (state, payload) => payload.name,
          },
        ],
      },
      listeners: () => ({
        updateName: () => {
          listenerRan1 = true
        },
      }),
    })

    firstLogic.extend({
      listeners: {
        updateName: () => {
          listenerRan2 = true
        },
      },
    })
    firstLogic.mount()

    firstLogic.actions.updateName('derpy')
    expect(firstLogic.values.name).toBe('derpy')

    expect(listenerRan1).toBe(true)
    expect(listenerRan2).toBe(true)
  })

  test('actions are bound', () => {
    let listenerRan1 = false
    let listenerRan2 = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'test'],
      actions: {
        updateName: (name) => ({ name }),
        updateOtherName: (name) => ({ name }),
      },
      listeners: ({ actions }) => ({
        updateName: () => {
          actions.updateOtherName()
          listenerRan1 = true
        },
        updateOtherName: () => {
          listenerRan2 = true
        },
      }),
    })

    firstLogic.mount()
    firstLogic.actions.updateName('derpy')

    expect(listenerRan1).toBe(true)
    expect(listenerRan2).toBe(true)
  })

  test('actions and values', () => {
    let listenerRan1 = false
    let listenerRan2 = false

    const firstLogic = kea({
      path: ['scenes', 'listeners', 'sharedListeners2'],
      actions: {
        updateName: (name) => ({ name }),
        updateOtherName: (name) => ({ name }),
      },
      reducers: {
        name: [
          'john',
          {
            updateName: (_, payload) => payload.name,
            updateOtherName: (_, payload) => payload.name,
          },
        ],
      },
      listeners: ({ actions, values }) => ({
        updateName: (payload, _, action) => {
          expect(payload.name).toBe('henry')

          expect(action.payload.name).toBe('henry')
          expect(action.payload).toBe(payload)
          expect(action.type).toBe(actions.updateName.toString())

          expect(values.name).toBe('henry')

          actions.updateOtherName('mike')
          expect(values.name).toBe('mike')

          listenerRan1 = true
        },
        updateOtherName: () => {
          listenerRan2 = true
        },
      }),
    })

    firstLogic.mount()
    firstLogic.actions.updateName('henry')

    expect(firstLogic.values.name).toBe('mike')

    expect(listenerRan1).toBe(true)
    expect(listenerRan2).toBe(true)
  })

  test('breakpoints', async () => {
    let listenerRan0 = 0
    let listenerRan1 = 0
    let listenerRan2 = 0

    let caught = 0
    let caughtNotBreakpoint = 0

    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
        setRepositories: (repositories) => ({ repositories }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, payload) => payload.username,
          },
        ],
        repositories: [
          [],
          {
            setRepositories: (_, payload) => payload.repositories,
          },
        ],
      },
      listeners: ({ actions }) => ({
        setUsername: async function (payload, breakpoint) {
          try {
            const { setRepositories } = actions

            listenerRan0 += 1
            await breakpoint(100) // debounce for 100ms
            listenerRan1 += 1

            // simulate response
            await delay(200)
            breakpoint()

            setRepositories([1, 2, 3])

            listenerRan2 += 1
          } catch (error) {
            caught += 1
            if (isBreakpoint(error)) {
              throw error
            }
            caughtNotBreakpoint += 1
          }
        },
      }),
    })

    firstLogic.mount()
    expect(firstLogic.values.repositories.length).toBe(0)
    expect(firstLogic.values.username).toBe('keajs')

    // these should trigger the "await breakpoint()"
    firstLogic.actions.setUsername('user1')
    firstLogic.actions.setUsername('user2')
    firstLogic.actions.setUsername('user3')
    firstLogic.actions.setUsername('user4')

    expect(firstLogic.values.username).toBe('user4')

    await delay(500)

    expect(listenerRan0).toBe(4)
    expect(listenerRan1).toBe(1)
    expect(listenerRan2).toBe(1)

    expect(caught).toBe(3)
    expect(caughtNotBreakpoint).toBe(0)

    expect(firstLogic.values.repositories.length).toBe(3)

    // this should trigger the breakpoint without await
    firstLogic.actions.setUsername('user1')
    await delay(200)
    firstLogic.actions.setUsername('user2')
    await delay(200)
    firstLogic.actions.setUsername('user3')

    expect(listenerRan0).toBe(7)
    expect(listenerRan1).toBe(3)
    expect(listenerRan2).toBe(1)

    await delay(500)

    expect(listenerRan0).toBe(7)
    expect(listenerRan1).toBe(4)
    expect(listenerRan2).toBe(2)

    expect(caught).toBe(5)
    expect(caughtNotBreakpoint).toBe(0)
  })

  test('breakpoints with two listeners for same action', async () => {
    let preListenerRan = 0
    let listenerRan0 = 0

    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
        setRepositories: (repositories) => ({ repositories }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, payload) => payload.username,
          },
        ],
        repositories: [
          [],
          {
            setRepositories: (_, payload) => payload.repositories,
          },
        ],
      },
      listeners: () => ({
        setUsername: [
          async function (payload, breakpoint) {
            await breakpoint(200)
            preListenerRan += 1
          },
          async function (payload, breakpoint) {
            await breakpoint(100)
            listenerRan0 += 1
          },
        ],
      }),
    })

    firstLogic.mount()

    firstLogic.actions.setUsername('user1')
    firstLogic.actions.setUsername('user4')

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(0)

    await delay(101)

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(1)

    firstLogic.actions.setUsername('user5')

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(1)

    await delay(201)

    expect(preListenerRan).toBe(1)
    expect(listenerRan0).toBe(2)
  })

  test('breakpoints with two listeners for same action after extending', async () => {
    let preListenerRan = 0
    let listenerRan0 = 0

    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
        setRepositories: (repositories) => ({ repositories }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, payload) => payload.username,
          },
        ],
        repositories: [
          [],
          {
            setRepositories: (_, payload) => payload.repositories,
          },
        ],
      },
      listeners: () => ({
        setUsername: async function (payload, breakpoint) {
          await breakpoint(200)
          preListenerRan += 1
        },
      }),
    })

    firstLogic.extend({
      listeners: () => ({
        setUsername: async function (payload, breakpoint) {
          await breakpoint(100)
          listenerRan0 += 1
        },
      }),
    })

    firstLogic.mount()

    firstLogic.actions.setUsername('user1')
    firstLogic.actions.setUsername('user4')

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(0)

    await delay(101)

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(1)

    firstLogic.actions.setUsername('user5')

    expect(preListenerRan).toBe(0)
    expect(listenerRan0).toBe(1)

    await delay(201)

    expect(preListenerRan).toBe(1)
    expect(listenerRan0).toBe(2)
  })

  test('breakpoints break when unmounting', async () => {
    let preListenerRan = 0
    let breakpointBroke = 0

    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, payload) => payload.username,
          },
        ],
      },
      listeners: {
        setUsername: async function (payload, breakpoint) {
          try {
            await breakpoint(100)
            preListenerRan += 1
          } catch (error) {
            if (isBreakpoint(error)) {
              breakpointBroke += 1
            }
          }
        },
      },
    })

    const unmount = firstLogic.mount()

    firstLogic.actions.setUsername('user1')
    await delay(10)
    unmount()
    await delay(100)

    expect(preListenerRan).toBe(0)
    expect(breakpointBroke).toBe(1)
  })

  test('breakpoints break when unmounting, they will not resume if mounting again', async () => {
    let preListenerRan = 0
    let breakpointBroke = 0

    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, payload) => payload.username,
          },
        ],
      },
      listeners: () => ({
        setUsername: async function (payload, breakpoint) {
          try {
            await breakpoint(100)
            preListenerRan += 1
          } catch (error) {
            if (isBreakpoint(error)) {
              breakpointBroke += 1
            }
          }
        },
      }),
    })

    const unmount = firstLogic.mount()
    firstLogic.actions.setUsername('user1')
    await delay(50)
    unmount()

    expect(preListenerRan).toBe(0)
    expect(breakpointBroke).toBe(0)

    // mount again
    const unmount2 = firstLogic.mount()
    firstLogic.actions.setUsername('user1')
    await delay(60)

    expect(preListenerRan).toBe(0)
    expect(breakpointBroke).toBe(1)

    unmount2()
    await delay(60)

    expect(preListenerRan).toBe(0)
    expect(breakpointBroke).toBe(2)
  })

  test("listeners get the store's previous state as their 4th argument", async () => {
    let listenerRan = false
    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
      },
      reducers: {
        username: [
          'keajs',
          {
            setUsername: (_, { username }) => username,
          },
        ],
      },
      listeners: ({ values, selectors }) => ({
        setUsername: async function (payload, breakpoint, action, previousState) {
          expect(values.username).toBe('user1')
          expect(selectors.username(previousState)).toBe('keajs')
          listenerRan = true
        },
      }),
    })

    const unmount = firstLogic.mount()
    expect(firstLogic.values.username).toBe('keajs')
    firstLogic.actions.setUsername('user1')
    expect(firstLogic.values.username).toBe('user1')
    expect(listenerRan).toBe(true)
    unmount()
  })

  test('track running listeners', async () => {
    const firstLogic = kea({
      actions: {
        setUsername: (username) => ({ username }),
      },
      listeners: {
        async setUsername(payload, breakpoint) {
          await breakpoint(100)
        },
      },
    })

    const unmount = firstLogic.mount()

    expect(getPluginContext('listeners').pendingPromises.size).toBe(0)
    expect(getPluginContext('listeners').pendingPromises.size).toBe(0)

    firstLogic.actions.setUsername('user1')
    expect(getPluginContext('listeners').pendingPromises.size).toBe(1)
    expect(Array.from(getPluginContext('listeners').pendingPromises.values())).toEqual([[firstLogic(), 'setUsername']])

    firstLogic.actions.setUsername('user1')
    expect(getPluginContext('listeners').pendingPromises.size).toBe(2)
    expect(Array.from(getPluginContext('listeners').pendingPromises.values())).toEqual([
      [firstLogic(), 'setUsername'],
      [firstLogic(), 'setUsername'],
    ])
    await delay(50)
    firstLogic.actions.setUsername('user1')
    expect(getPluginContext('listeners').pendingPromises.size).toBe(3)
    await delay(50)
    expect(getPluginContext('listeners').pendingPromises.size).toBe(1)
    await delay(50)
    expect(getPluginContext('listeners').pendingPromises.size).toBe(0)

    unmount()
  })

  test('context change breaks breakpoints', async () => {
    const gotThem = []
    const logic = kea({
      actions: {
        setUsername: (username) => ({ username }),
      },
      listeners: {
        async setUsername({ username }, breakpoint) {
          await breakpoint(100)
          gotThem.push(username)
        },
      },
    })

    resetContext()
    logic.mount()
    logic.actions.setUsername('context1')
    await delay(50)

    resetContext()
    logic.mount()
    logic.actions.setUsername('context2')
    await delay(100)

    expect(gotThem).toEqual(['context2'])
  })

  test('can listen to actions that were not yet added', () => {
    resetContext()
    let logic1Listenerd = false
    let logic2Listenerd = false
    const logic1 = kea([
      listeners({
        undefinedAction: () => {
          logic1Listenerd = true
        },
      }),
      actions({ undefinedAction: true }),
    ])
    const logic2 = kea([
      actions({ definedAction: true }),
      listeners({
        definedAction: () => {
          logic2Listenerd = true
        },
      }),
    ])

    logic1.mount()
    logic1.actions.undefinedAction()
    expect(logic1Listenerd).toEqual(true)

    logic2.mount()
    logic2.actions.definedAction()
    expect(logic1Listenerd).toEqual(true)
  })
})
