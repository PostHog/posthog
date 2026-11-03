import { kea, actions, reducers, resetContext } from '../../src'

describe('reducers', () => {
  test('it converts reducer arrays correctly', () => {
    resetContext()

    const reducerFunction = (state) => state

    const logic = kea({
      defaults: () => ({
        milk: 'not found',
      }),

      reducers: () => ({
        null: [],
        noPropNoOptions: [0, { ACTION: reducerFunction }],
        onlyDefault: [0],
        withoutDefault: { ACTION: reducerFunction },
      }),
    })

    logic.mount()

    expect(Object.keys(logic.reducers).sort()).toEqual(['noPropNoOptions', 'null', 'onlyDefault', 'withoutDefault'])
    expect(Object.keys(logic.defaults).sort()).toEqual([
      'milk',
      'noPropNoOptions',
      'null',
      'onlyDefault',
      'withoutDefault',
    ])
    expect(typeof logic.reducers.null).toBe('function')
    expect(typeof logic.reducers.noPropNoOptions).toBe('function')
    expect(typeof logic.reducers.onlyDefault).toBe('function')
    expect(typeof logic.reducers.withoutDefault).toBe('function')

    expect(logic.defaults.milk).toBe('not found')
    expect(logic.defaults.null).toBe(null)
    expect(logic.defaults.noPropNoOptions).toBe(0)
    expect(logic.defaults.onlyDefault).toBe(0)
    expect(logic.defaults.withoutDefault).toBe(null)
  })

  test('it auto-detects local actions from the key in reducers', () => {
    resetContext()

    const logic = kea({
      actions: () => ({
        makeMagic: true,
        moreMagic: (value) => ({ value }),
      }),

      defaults: { howMuchMagic: 0 },

      reducers: ({ actions }) => ({
        howMuchMagic: {
          makeMagic: (state) => state + 1,
          [actions.moreMagic]: (state, { value }) => state + value,
        },
      }),
    })

    logic.mount()

    expect(Object.keys(logic.reducers).sort()).toEqual(['howMuchMagic'])

    expect(logic.defaults.howMuchMagic).toEqual(0)
    expect(logic.values.howMuchMagic).toEqual(0)

    logic.actions.makeMagic()

    expect(logic.values.howMuchMagic).toEqual(1)

    logic.actions.moreMagic(100)

    expect(logic.values.howMuchMagic).toEqual(101)
  })

  test('it extends reducers instead of overriding them', () => {
    resetContext()

    const logic = kea({
      actions: () => ({
        simpleMagic: true,
        makeMagic: true,
        makeABitMoreMagic: true,
      }),

      reducers: ({ actions }) => ({
        howMuchMagic: [
          0,
          {
            simpleMagic: (state) => state + 1,
            makeMagic: (state) => state + 1,
          },
        ],
      }),
    })

    logic.extend({
      actions: () => ({
        moreMagic: true,
      }),

      reducers: ({ actions }) => ({
        howMuchMagic: [
          0,
          {
            makeMagic: (state) => state + 2,
            moreMagic: (state) => state + 100,
          },
        ],
      }),
    })

    logic.mount()
    expect(logic.values.howMuchMagic).toEqual(0)

    logic.actions.makeMagic()
    expect(logic.values.howMuchMagic).toEqual(2)

    logic.actions.moreMagic()
    expect(logic.values.howMuchMagic).toEqual(102)

    logic.actions.makeMagic()
    expect(logic.values.howMuchMagic).toEqual(104)
  })

  test('reducerOptions', () => {
    resetContext()

    const logic = kea({
      actions: () => ({
        simpleMagic: true,
        makeMagic: true,
        makeABitMoreMagic: true,
      }),

      reducers: {
        howMuchMagic: [
          0,
          { reducerOptions: 'options' },
          {
            simpleMagic: (state) => state + 1,
            makeMagic: (state) => state + 1,
          },
        ],
      },
    })

    logic.mount()
    expect(logic.reducerOptions['howMuchMagic']).toEqual({ reducerOptions: 'options' })
  })

  test('can reduce to actions that were not yet added', () => {
    resetContext()
    const logic1 = kea([reducers({ value: { undefinedAction: () => true } }), actions({ undefinedAction: true })])
    const logic2 = kea([actions({ definedAction: true }), reducers({ value: { definedAction: () => true } })])

    logic1.mount()
    logic1.actions.undefinedAction()
    expect(logic1.values.value).toEqual(true)

    logic2.mount()
    logic2.actions.definedAction()
    expect(logic2.values.value).toEqual(true)
  })
})
