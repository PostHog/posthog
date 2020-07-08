export interface userLogicType<UserType> {
    actionCreators: {
        loadUser: () => ({
            type: string;
            payload: {
                value: boolean;
            };
        });
        setUser: (user: UserType | null, updateKey?: string) => ({
            type: string;
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({
            type: string;
            payload: { update: Partial<UserType>; updateKey: string | undefined; };
        });
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({
            type: string;
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateFailure: (error: string, updateKey?: string) => ({
            type: string;
            payload: { updateKey: string | undefined; error: string; };
        });
    };
    actions: {
        loadUser: () => ({
            type: string;
            payload: {
                value: boolean;
            };
        });
        setUser: (user: UserType | null, updateKey?: string) => ({
            type: string;
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({
            type: string;
            payload: { update: Partial<UserType>; updateKey: string | undefined; };
        });
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({
            type: string;
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateFailure: (error: string, updateKey?: string) => ({
            type: string;
            payload: { updateKey: string | undefined; error: string; };
        });
    };
    reducer: (state: any, action: () => any, fullState: any) => {
        user: UserType | null;
    };
    reducers: {
        user: (state: UserType | null, action: any, fullState: any) => UserType | null;
    };
    selector: (state: any) => {
        user: UserType | null;
    };
    selectors: {
        user: (state: any, props: any) => UserType | null;
        eventProperties: (state: any, props: any) => { value: string; label: string; }[] | undefined;
        eventNames: (state: any, props: any) => string[] | undefined;
        customEventNames: (state: any, props: any) => string[];
        eventNamesGrouped: (state: any, props: any) => { label: string; options: { label: string; value: string; }[]; }[];
    };
    values: {
        user: UserType | null;
        eventProperties: { value: string; label: string; }[] | undefined;
        eventNames: string[] | undefined;
        customEventNames: string[];
        eventNamesGrouped: { label: string; options: { label: string; value: string; }[]; }[];
    };
}