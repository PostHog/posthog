import { kea, getContext, resetContext, reducers, selectors, path } from '../../src'
import { unmountedActionError } from '../../src/kea/kea'

describe('errors', () => {
  beforeEach(() => {
    resetContext({ createStore: true })
  })

  test('connected logics', () => {
    const expectedErrorMessage = unmountedActionError('actions', 'kea.logic.1')

    const secondLogic = kea({
      actions: ({}) => ({
        doSomethingElse: true,
      }),
      reducers: ({ actions }) => ({
        wotsit: [
          false,
          {
            [actions.doSomethingElse]: () => true,
          },
        ],
      }),
    })

    const firstLogic = () =>
      kea({
        connect: {
          logics: [secondLogic],
        },
        actions: {
          doSomething: true,
        },
        reducers: {
          thingie: [
            false,
            {
              doSomething: () => true,
              [secondLogic.actions.wotsit]: () => false,
            },
          ],
        },
      })

    expect(() => firstLogic().build()).toThrow(expectedErrorMessage)
  })

  test('building broken selectors throws a nice error', () => {
    const { store } = getContext()

    const logic = kea({
      actions: ({}) => ({
        doSomething: true,
      }),
      reducers: ({ actions }) => ({
        thingie: [
          false,
          {
            [actions.doSomething]: () => true,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        anotherThing: [() => [selectors.thingie, selectors.notFound], (thingie, notFound) => 'whatever'],
      }),
    })

    expect(() => {
      logic.build()
    }).toThrow('[KEA] Logic "kea.logic.1", selector "anotherThing" has incorrect input: [function, undefined].')
  })

  test('connecting to something that does not exist gives an error', () => {
    const { store } = getContext()

    const logic = kea({})
    logic.build() // no error

    expect(() => {
      kea({
        connect: {
          values: [undefined, ['notThere']],
        },
      }).build()
    }).toThrow('[KEA] Logic "kea.logic.2" can not connect to undefined to request prop "notThere"')

    expect(() => {
      kea({
        connect: {
          values: ['haha', ['notThere']],
        },
      }).build()
    }).toThrow('[KEA] Logic "kea.logic.3" can not connect to string to request prop "notThere"')

    expect(() => {
      kea({
        connect: {
          actions: [undefined, ['notThere']],
        },
      }).build()
    }).toThrow('[KEA] Logic "kea.logic.4" can not connect to undefined to request action "notThere"')

    expect(() => {
      kea({
        connect: {
          actions: [logic, ['notThere']],
        },
      }).build()
    }).toThrow('[KEA] Logic "kea.logic.5", connecting to action "notThere" returns \'undefined\'')

    expect(() => {
      kea({
        connect: {
          actions: ['haha', ['notThere']],
        },
      }).build()
    }).toThrow('[KEA] Logic "kea.logic.6" can not connect to string to request action "notThere"')
  })

  test('reducers with undefined actions throw', () => {
    const logic = kea({
      actions: () => ({
        doSomething: true,
      }),
      reducers: ({ actions }) => ({
        thingie: [
          false,
          {
            [actions.doSomething]: () => true,
            [actions.nope]: () => false,
          },
        ],
      }),
    })

    expect(() => {
      logic.build()
    }).toThrow(
      '[KEA] Logic "kea.logic.1" reducer "thingie" is waiting for an action that is undefined: [do something (kea.logic.1), undefined]',
    )
  })

  test('using actions before mounting throws', () => {
    const logic = kea({
      path: () => ['kea', 'random'],
      actions: () => ({
        doSomething: true,
      }),
      reducers: ({ actions }) => ({
        thingie: [
          false,
          {
            [actions.doSomething]: () => true,
          },
        ],
      }),
    })

    expect(() => logic.actions.doSomething()).toThrow()

    expect(() => logic.values.thingie).toThrow()

    const logic2 = kea({
      actions: () => ({
        doSomething: true,
      }),
      reducers: ({ actions }) => ({
        thingie: [
          false,
          {
            [actions.doSomething]: () => true,
          },
        ],
      }),
    })

    expect(() => logic2.actions.doSomething()).toThrow()
  })

  test('paths that lead nowhere throw decent errors', () => {
    const { store } = getContext()

    const logic = kea({
      path: ['scenes', 'misc', 'foo'],
      actions: {
        doSomething: true,
      },
      reducers: {
        thingie: [
          false,
          {
            doSomething: () => true,
          },
        ],
      },
    })

    const unmount = logic.mount()
    const state = store.getState()

    state.scenes = {}
    expect(() => {
      logic.values.thingie
    }).toThrow('[KEA] Can not find path "scenes.misc.foo" in the store.')

    unmount()
  })

  test('creating too many selectors or reducers', () => {
    expect(() => {
      kea([
        path(['first']),
        reducers({
          something: [true],
        }),
        selectors({
          somethingElse: [(s) => [], () => null],
        }),
      ]).mount()
    }).not.toThrow()

    expect(() => {
      kea([
        path(['second']),
        reducers({
          something: [true],
        }),
        selectors({
          something: [(s) => [], () => null],
        }),
      ]).mount()
    }).toThrow('[KEA] Logic "second" selector "something" already exists')

    expect(() => {
      kea([
        path(['second']),
        selectors({
          something: [(s) => [], () => null],
        }),
        selectors({
          something: [(s) => [], () => null],
        }),
      ]).mount()
    }).toThrow('[KEA] Logic "second" selector "something" already exists')

    expect(() => {
      kea([
        path(['third']),
        selectors({
          something: [(s) => [], () => null],
        }),
        reducers({
          something: [true],
        }),
      ]).mount()
    }).toThrow('[KEA] Logic "third" can\'t add reducer "something" because a selector with the same name exists.')

    expect(() => {
      kea([
        path(['third']),
        reducers({
          something: [true],
        }),
        reducers({
          something: [true],
        }),
      ]).mount()
    }).not.toThrow()
  })
})
