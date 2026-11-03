import { kea, resetContext, getContext, path, key } from '../../src'

describe('mount', () => {
  beforeEach(() => {
    resetContext()
  })

  test('can mount stores and have them connect to redux without react', () => {
    const { store } = getContext()

    const logic = kea({
      path: () => ['scenes', 'lazy'],
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

    // nothing yet in the store
    expect(store.getState()).toEqual({ kea: {} })

    const unmount = logic.mount()

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { name: 'chirpy' } } })

    store.dispatch(logic.actionCreators.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { name: 'somename' } } })

    unmount()

    // nothing in the store after unmounting
    expect(store.getState()).toEqual({ kea: {} })
  })

  test('can mount stores with keys and have them connet to redux without react', () => {
    const { store } = getContext()

    const logic = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'lazy', key],
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

    // nothing yet in the store
    expect(store.getState()).toEqual({ kea: {} })

    const unmount = logic({ id: 'testKey' }).mount()

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { testKey: { name: 'chirpy' } } } })

    store.dispatch(logic({ id: 'testKey' }).actionCreators.updateName('somename'))

    expect(store.getState()).toEqual({ kea: {}, scenes: { lazy: { testKey: { name: 'somename' } } } })

    unmount()

    // nothing in the store after unmounting
    expect(store.getState()).toEqual({ kea: {} })
  })

  describe('can get mounted state with isMounted', () => {
    test('logicWrapper', async () => {
      const logic = kea({})
      expect(logic.isMounted()).toEqual(false)
      const u1 = logic.mount()
      expect(logic.isMounted()).toEqual(true)
      const u2 = logic.mount()
      expect(logic.isMounted()).toEqual(true)
      u1()
      expect(logic.isMounted()).toEqual(true)
      u2()
      expect(logic.isMounted()).toEqual(false)
      expect(() => u2()).toThrow()
      expect(logic.isMounted()).toEqual(false)
      logic.mount()
      expect(logic.isMounted()).toEqual(true)
    })

    test('isMounted/findMounted() on logicWrapper does not build', () => {
      const logic = kea({})
      const isLogicBuilt = () => !!getContext().wrapperContexts.get(logic)?.builtLogics.get(undefined)
      expect(isLogicBuilt()).toBeFalsy()
      expect(logic.isMounted()).toEqual(false)
      expect(logic.findMounted()).toEqual(null)
      expect(() => {
        logic.find()
      }).toThrowError('[KEA] Can not find mounted logic')
      expect(isLogicBuilt()).toBeFalsy()
      const u1 = logic.mount()
      expect(isLogicBuilt()).toBeTruthy()
      expect(logic.isMounted()).toEqual(true)
      expect(logic.findMounted()).toEqual(logic())
      expect(logic.find()).toEqual(logic())
      u1()
      expect(isLogicBuilt()).toBeFalsy()
    })

    test('isMounted() on logicWrapper with a key and no props returns false', () => {
      const logic = kea({ key: ({ id }) => id })
      expect(logic.isMounted()).toBeFalsy()
    })

    test('isMounted/findMounted/find() on logicWrapper accepts props', () => {
      const logic = kea({ key: ({ id }) => id })
      expect(logic.isMounted({ id: 12 })).toEqual(false)
      expect(logic.isMounted(12)).toEqual(false)
      expect(logic.findMounted({ id: 12 })).toEqual(null)
      expect(logic.findMounted(12)).toEqual(null)
      expect(() => {
        logic.find({ id: 12 })
      }).toThrowError('[KEA] Can not find mounted logic with props {"id":12}')
      expect(() => {
        logic.find(12)
      }).toThrowError('[KEA] Can not find mounted logic with key 12')

      logic({ id: 12 }).mount()
      expect(logic.isMounted({ id: 12 })).toEqual(true)
      expect(logic.isMounted(12)).toEqual(true)
      expect(logic.findMounted({ id: 12 })).toEqual(logic({ id: 12 }))
      expect(logic.findMounted(12)).toEqual(logic({ id: 12 }))
      expect(logic.find({ id: 12 })).toEqual(logic({ id: 12 }))
      expect(logic.find(12)).toEqual(logic({ id: 12 }))
    })

    test('findAllMounted() on logicWrapper does not build', () => {
      const logic = kea({})
      const isLogicBuilt = () => !!getContext().wrapperContexts.get(logic)?.builtLogics.get(undefined)
      expect(isLogicBuilt()).toBeFalsy()
      expect(logic.findAllMounted()).toEqual([])
      expect(isLogicBuilt()).toBeFalsy()
      const u1 = logic.mount()
      expect(isLogicBuilt()).toBeTruthy()
      expect(logic.findAllMounted()).toEqual([logic()])
      u1()
      expect(logic.findAllMounted()).toEqual([])
    })

    test('findAllMounted() returns all mounted logics with keys', () => {
      const logic = kea({ key: ({ id }) => id })
      const l1 = logic({ id: 12 })
      const l2 = logic({ id: 33 })
      const u1 = l1.mount()
      const u2 = l2.mount()
      expect(logic.findAllMounted()).toEqual([l1, l2])
      u1()
      expect(logic.findAllMounted()).toEqual([l2])
      u2()
      expect(logic.findAllMounted()).toEqual([])
    })

    test('buildLogic', async () => {
      const logic = kea({}).build()
      expect(logic.isMounted()).toEqual(false)
      const u1 = logic.mount()
      expect(logic.isMounted()).toEqual(true)
      const u2 = logic.mount()
      expect(logic.isMounted()).toEqual(true)
      u1()
      expect(logic.isMounted()).toEqual(true)
      u2()
      expect(logic.isMounted()).toEqual(false)
      expect(() => u2()).toThrow()
      expect(logic.isMounted()).toEqual(false)
      logic.mount()
      expect(logic.isMounted()).toEqual(true)
    })
  })

  test('can mount logic with default key', () => {
    const logic = kea([path((key) => ['scenes', 'misc', key]), key(({ id }) => id ?? 'default')])
    logic.mount()
    expect(logic.isMounted()).toEqual(true)
  })
})
