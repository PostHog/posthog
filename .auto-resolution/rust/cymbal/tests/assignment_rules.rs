use std::collections::HashMap;

use chrono::Utc;
use cymbal::{
    assignment_rules::{AssignmentRule, NewAssignment},
    config::Config,
    fingerprinting::Fingerprint,
    issue_resolution::{process_assignment, Issue, IssueStatus},
    teams::TeamManager,
    types::{ExceptionList, FingerprintedErrProps},
};
use serde_json::{json, Value as JsonValue};
use sqlx::PgPool;
use uuid::Uuid;

fn rule_bytecode() -> JsonValue {
    // return properties.test_value = 'test_value'
    json!([
        "_H",
        1,
        32,
        "test_value",
        32,
        "test_value",
        32,
        "properties",
        1,
        2,
        11,
        38
    ])
}

fn get_test_rule() -> AssignmentRule {
    AssignmentRule {
        id: Uuid::new_v4(),
        team_id: 1,
        user_id: Some(1), // This rule assigns the issue to user with ID 1
        role_id: None,
        order_key: 1,
        bytecode: rule_bytecode(),
        created_at: Utc::now(),
        updated_at: Utc::now(),
    }
}

fn test_fingerprint() -> Fingerprint {
    Fingerprint {
        value: String::from("test value"),
        record: vec![],
        assignment: None,
    }
}

fn test_props(fingerprint: Fingerprint) -> FingerprintedErrProps {
    FingerprintedErrProps {
        exception_list: ExceptionList(vec![]),
        fingerprint,
        proposed_issue_name: None,
        proposed_issue_description: None,
        proposed_fingerprint: String::new(),
        other: HashMap::new(),
    }
}

fn test_issue() -> Issue {
    Issue {
        id: Uuid::now_v7(),
        team_id: 1,
        status: IssueStatus::Active,
        name: None,
        description: None,
    }
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_assignment_processing(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();

    let fingerprint = test_fingerprint();
    let test_team_id = 1;
    let mut test_props = test_props(fingerprint);
    test_props
        .other
        .insert("test_value".to_string(), JsonValue::from("test_value"));

    let issue = test_issue();

    let rule = get_test_rule();
    let team_manager = TeamManager::new(&config);
    // Insert the rule, so we skip the DB lookup
    team_manager
        .assignment_rules
        .insert(test_team_id, vec![rule]);

    let mut conn = db.acquire().await.unwrap();

    let res = process_assignment(&mut conn, &team_manager, &issue, test_props.clone())
        .await
        .unwrap();

    assert!(res.is_some());
    let res = res.unwrap();

    // Assert that the assignment returned is the one from the rule, because the fingerprint has no assignment
    assert!(test_props.fingerprint.assignment.is_none());
    assert!(res.user_id.is_some());
    assert_eq!(res.user_id.unwrap(), 1);

    let existing = res;

    // Now, do the assignment again, but this time assigning a different user. The original assignment should be
    // returned, since we want to respect existing assignments when processing exceptions, and we're re-using the
    // issue
    let mut rule = get_test_rule();
    rule.user_id = Some(2);

    team_manager
        .assignment_rules
        .insert(test_team_id, vec![rule]);

    let res = process_assignment(&mut conn, &team_manager, &issue, test_props.clone())
        .await
        .unwrap();

    assert!(res.is_some());
    let res = res.unwrap();
    assert_eq!(res.user_id, existing.user_id);
    assert_eq!(res.role_id, existing.role_id);

    // Next, change the issue, and put an assignment on the fingerprint. The returned assignment should be the one from
    // the fingerprint, rather than the rule, because fingerprint assignments take priority over assignment rules

    let mut props_with_fingerprint_assignment = test_props.clone();
    let fingerprint_assignment = NewAssignment::try_new(Some(3), None).unwrap();
    props_with_fingerprint_assignment.fingerprint.assignment = Some(fingerprint_assignment);

    let mut new_issue = issue.clone();
    new_issue.id = Uuid::now_v7(); // So we don't hit the "respect existing assignments" path

    let res = process_assignment(
        &mut conn,
        &team_manager,
        &new_issue,
        props_with_fingerprint_assignment.clone(),
    )
    .await
    .unwrap();

    assert!(res.is_some());
    let res = res.unwrap();
    assert_eq!(res.user_id, Some(3));
    assert_eq!(res.role_id, None);
}
