import { kea } from '../../src'
import { resetContext } from '../../src'

describe('extend', () => {
  beforeEach(() => {
    resetContext()
  })

  test('can not extend when mounted', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit'])

    expect(() => {
      logic.extend({
        actions: () => ({
          domore: true,
        }),
      })
    }).toThrowError('[KEA] Can not extend logic once it has been built.')
  })

  test('can extend with .extend', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
    })

    logic.extend({
      actions: () => ({
        domore: true,
      }),
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend with .extend', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
    }).extend({
      actions: () => ({
        domore: true,
      }),
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend with extend: []', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      extend: [
        {
          actions: () => ({
            domore: true,
          }),
        },
      ],
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend multiple times with .extend', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
    })

    logic.extend({
      actions: () => ({
        domore: true,
      }),
    })

    logic.extend({
      actions: () => ({
        doevenmore: true,
      }),
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])
  })

  test('can extend multiple times with .extend', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
    })
      .extend({
        actions: () => ({
          domore: true,
        }),
      })
      .extend({
        actions: () => ({
          doevenmore: true,
        }),
      })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])
  })

  test('can extend multiple times with extend: []', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      extend: [
        {
          actions: () => ({
            domore: true,
          }),
        },
        {
          actions: () => ({
            doevenmore: true,
          }),
        },
      ],
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])
  })

  test('can extend multiple recursive times with extend: []', () => {
    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      extend: [
        {
          actions: () => ({
            domore: true,
          }),
          extend: [
            {
              actions: () => ({
                doevenmore: true,
              }),
            },
          ],
        },
      ],
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])
  })

  test('can extend in plugins in beforeBuild', () => {
    const testPlugin = {
      name: 'testPlugin',
      events: {
        beforeBuild(logic, input) {
          logic.extend({
            actions: () => ({
              domore: true,
            }),
          })
        },
      },
    }

    resetContext({ plugins: [testPlugin] })

    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      plugins: [testPlugin],
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend in plugins in legacyBuild', () => {
    const testPlugin = {
      name: 'testPlugin',
      events: {
        legacyBuild(logic, input) {
          if (!logic.actions.domore) {
            logic.extend({
              actions: () => ({
                domore: true,
              }),
            })
          }
        },
      },
    }

    resetContext({ plugins: [testPlugin] })

    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      plugins: [testPlugin],
    })

    expect(Object.keys(logic.build().actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend in plugins in afterBuild', () => {
    const testPlugin = {
      name: 'testPlugin',
      events: {
        afterBuild(logic, input) {
          logic.extend({
            actions: () => ({
              domore: true,
            }),
          })
        },
      },
    }

    resetContext({ plugins: [testPlugin] })

    const logic = kea({
      actions: () => ({
        doit: true,
      }),
      plugins: [testPlugin],
    })

    logic.mount()

    expect(Object.keys(logic.actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend dynamic logic with extend:[]', () => {
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'something', key],
      actions: () => ({
        doit: true,
      }),
      extend: [
        {
          actions: () => ({
            domore: true,
          }),
        },
      ],
    })

    expect(Object.keys(logic({ id: 123 }).actions).sort()).toEqual(['doit', 'domore'])
  })

  test('can extend dynamic logic with .extend', () => {
    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'something', key],
      actions: () => ({
        doit: true,
      }),
    }).extend({
      actions: () => ({
        domore: true,
      }),
    })

    expect(Object.keys(logic({ id: 123 }).actions).sort()).toEqual(['doit', 'domore'])
  })

  test('extending logic merges the right properties', () => {
    const logic = kea({
      path: () => ['scenes', 'homepage', 'index'],
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
      extend: [
        {
          actions: () => ({
            updateDescription: (description) => ({ description }),
          }),
          reducers: ({ actions }) => ({
            description: [
              '',
              {
                [actions.updateDescription]: (state, payload) => payload.description,
              },
            ],
          }),
          selectors: ({ selectors }) => ({
            upperCaseDescription: [() => [selectors.description], (description) => description.toUpperCase()],
          }),
        },
      ],
    })

    logic.mount()

    // check generic
    expect(logic._isKea).toBe(true)
    expect(logic.path).toEqual(['scenes', 'homepage', 'index'])
    expect(Object.keys(logic.connections)).toEqual(['scenes.homepage.index'])

    // actions
    expect(Object.keys(logic.actions)).toEqual(['updateName', 'updateDescription'])
    const { updateName, updateDescription } = logic.actionCreators
    expect(typeof updateDescription).toBe('function')
    expect(updateDescription.toString()).toBe('update description (scenes.homepage.index)')
    expect(updateDescription('desc desc')).toEqual({
      payload: { description: 'desc desc' },
      type: updateDescription.toString(),
    })

    // reducers
    const defaultValues = { name: 'chirpy', description: '' }
    const state = { scenes: { homepage: { index: defaultValues } } }
    expect(Object.keys(logic.reducers).sort()).toEqual(['description', 'name'])

    expect(logic.reducers).toHaveProperty('name')
    expect(logic.reducers).toHaveProperty('description')
    expect(logic.defaults.name).toEqual('chirpy')

    const nameReducer = logic.reducers.name
    expect(nameReducer).toBeDefined()
    expect(nameReducer('', updateName('newName'))).toBe('newName')

    expect(logic.reducers).not.toHaveProperty('capitalizedName')
    expect(logic.defaults).not.toHaveProperty('capitalizedName', 'chirpy')

    // big reducer
    expect(typeof logic.reducer).toBe('function')
    expect(logic.reducer({}, { type: 'random action' })).toEqual(defaultValues)
    expect(logic.reducer({ description: 'desc desc', name: 'something' }, { type: 'random action' })).toEqual({
      description: 'desc desc',
      name: 'something',
    })

    expect(logic.reducer({ description: 'desc desc', name: 'something' }, updateName('newName'))).toEqual({
      description: 'desc desc',
      name: 'newName',
    })

    // selectors
    expect(Object.keys(logic.selectors).sort()).toEqual([
      'capitalizedName',
      'description',
      'name',
      'upperCaseDescription',
      'upperCaseName',
    ])
    expect(logic.selectors.name(state)).toEqual('chirpy')
    expect(logic.selectors.capitalizedName(state)).toEqual('Chirpy')
    expect(logic.selectors.upperCaseName(state)).toEqual('CHIRPY')

    const defaultValues2 = { name: 'chirpy', description: 'tsk tsk' }
    const state2 = { scenes: { homepage: { index: defaultValues2 } } }
    expect(logic.reducer({ description: 'tsk tsk', name: 'something' }, updateName('newName'))).toEqual({
      description: 'tsk tsk',
      name: 'newName',
    })

    expect(logic.selectors.description(state2)).toEqual('tsk tsk')
    expect(logic.selectors.upperCaseDescription(state2)).toEqual('TSK TSK')

    // root selector
    expect(logic.selector(state)).toEqual(defaultValues)
  })

  test('can do inheritance with .inputs', () => {
    const logic = kea({
      path: ['first'],
      actions: {
        doit: true,
      },
    })

    const logic2 = kea({
      path: ['second'],
      extend: [
        ...logic.inputs,
        {
          actions: {
            domore: true,
          },
        },
      ],
    })

    const logic3 = kea({
      path: ['third'],
      extend: [
        ...logic2.inputs,
        {
          actions: {
            doevenmore: true,
          },
        },
      ],
    })

    const unmount = logic.mount()
    const unmount2 = logic2.mount()
    const unmount3 = logic3.mount()

    expect(Object.keys(logic.actions).sort()).toEqual(['doit'])
    expect(Object.keys(logic2.actions).sort()).toEqual(['doit', 'domore'])
    expect(Object.keys(logic3.actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])

    expect(logic.path).toEqual(['first'])
    expect(logic2.path).toEqual(['second'])
    expect(logic3.path).toEqual(['third'])

    unmount()
    unmount2()
    unmount3()
  })

  test('can do inheritance with inherit', () => {
    const logic = kea({
      path: ['first'],
      actions: {
        doit: true,
      },
    })

    const logic2 = kea({
      path: ['second'],
      inherit: [logic],
      actions: {
        domore: true,
      },
    })

    const logic3 = kea({
      path: ['third'],
      inherit: [logic2],
      actions: {
        doevenmore: true,
      },
    })

    const unmount = logic.mount()
    const unmount2 = logic2.mount()
    const unmount3 = logic3.mount()

    expect(Object.keys(logic.actions).sort()).toEqual(['doit'])
    expect(Object.keys(logic2.actions).sort()).toEqual(['doit', 'domore'])
    expect(Object.keys(logic3.actions).sort()).toEqual(['doevenmore', 'doit', 'domore'])

    expect(logic.path).toEqual(['first'])
    expect(logic2.path).toEqual(['second'])
    expect(logic3.path).toEqual(['third'])

    unmount()
    unmount2()
    unmount3()
  })
})
