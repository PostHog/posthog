import { kea, resetContext } from '../../src'

describe('simplified objects', () => {
  beforeEach(() => {
    resetContext()
  })

  test('it works without () => ({}) and just with {}', () => {
    let iveBeen

    const logic = kea({
      path: ['something', 'album'],
      actions: {
        setFlunk: (flunk) => ({ flunk }),
      },
      reducers: {
        flunk: {
          setFlunk: (_, { flunk }) => flunk,
        },
      },
      defaults: {
        flunk: 'whatitmeans',
      },
      selectors: {
        someOtherSelector: [() => [], () => 'downdowndown'],
      },
      listeners: {
        setFlunk: () => {
          iveBeen = logic.values.someOtherSelector
        },
      },
      events: {
        afterMount() {
          iveBeen = 'up'
        },
      },
    })

    const umount = logic.mount()

    expect(iveBeen).toBe('up')

    expect(Object.keys(logic.actions)).toEqual(['setFlunk'])
    expect(Object.keys(logic.reducers)).toEqual(['flunk'])
    expect(Object.keys(logic.selectors)).toEqual(['flunk', 'someOtherSelector'])

    expect(logic.values.flunk).toBe('whatitmeans')
    logic.actions.setFlunk('donotknow')
    expect(logic.values.flunk).toBe('donotknow')
    expect(iveBeen).toBe('downdowndown')

    umount()
  })

  test('how far can I push this syntax? new selectors!', () => {
    const konsole = { messages: [], log: (msg) => konsole.messages.push(msg) }
    const logic = kea({
      actions: {
        goUp: true,
        goDown: true,
        setFloor: (floor) => ({ floor }),
      },
      reducers: {
        floor: [
          1,
          {
            goUp: (state) => state + 1,
            goDown: (state) => state - 1,
            setFloor: (_, { floor }) => floor,
          },
        ],
      },
      selectors: {
        systemState: [(selectors) => [selectors.floor], (floor) => (floor < 1 || floor > 20 ? 'broken' : 'working')],
      },
      listeners: {
        setFloor: ({ floor }) => {
          if (floor < 1 || floor > 20) {
            konsole.log('you broke the system!')
          }
          if (logic.values.systemState === 'broken') {
            konsole.log('error, error!')
          }
        },
      },
    })

    logic.mount()

    expect(logic.values.floor).toBe(1)
    logic.actions.goUp()
    expect(logic.values.floor).toBe(2)
    logic.actions.goDown()
    expect(logic.values.floor).toBe(1)
    expect(logic.values.systemState).toBe('working')

    logic.actions.setFloor(30)
    expect(logic.values.floor).toBe(30)
    expect(logic.values.systemState).toBe('broken')

    expect(konsole.messages).toEqual(['you broke the system!', 'error, error!'])
  })
})
