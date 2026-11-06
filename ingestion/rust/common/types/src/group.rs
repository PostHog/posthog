use sqlx::Postgres;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct GroupType {
    pub id: i32,
    pub group_type: String,
    pub group_type_index: i32,
    pub team_id: i32,
}

impl GroupType {
    pub async fn for_index<'c, E>(
        e: E,
        team_id: i32,
        index: i32,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            "SELECT id, group_type, group_type_index, team_id FROM posthog_grouptypemapping WHERE team_id = $1 AND group_type_index = $2",
            team_id,
            index
        )
        .fetch_optional(e)
        .await
    }

    pub async fn for_name<'c, E>(
        e: E,
        team_id: i32,
        name: &str,
    ) -> Result<Option<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            "SELECT id, group_type, group_type_index, team_id FROM posthog_grouptypemapping WHERE team_id = $1 AND group_type = $2",
            team_id,
            name
        )
        .fetch_optional(e)
        .await
    }

    pub async fn for_team<'c, E>(e: E, team_id: i32) -> Result<Vec<Self>, sqlx::Error>
    where
        E: sqlx::Executor<'c, Database = Postgres>,
    {
        sqlx::query_as!(
            Self,
            "SELECT id, group_type, group_type_index, team_id FROM posthog_grouptypemapping WHERE team_id = $1",
            team_id
        )
        .fetch_all(e)
        .await
    }
}
