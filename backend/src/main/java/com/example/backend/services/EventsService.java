package com.example.backend.services;

import java.text.DecimalFormat;
import java.time.LocalDateTime;
import java.util.*;

import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.stereotype.Service;

import com.example.backend.model.*;

import java.sql.*;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.springframework.jdbc.core.RowCallbackHandler;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.nio.file.Files;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.util.List;


/**
 * eventsService
 */
@Service
@SpringBootApplication(exclude = { DataSourceAutoConfiguration.class })
public class EventsService {

    private final String url = "jdbc:ch://localhost:8123";
    private final String username = "default";
    private final String password = "";
    private Statement st;
    private Connection con;

    public EventsService() {
        try {
            con = DriverManager.getConnection(url, username, password);
            System.out.println("Connection is successfully");

            st = con.createStatement();
        } catch (SQLException ex) {
            System.out.println(ex);
        }
    }

    // TODO: Delete All Events.
    public void deleteAllEvents() {
        try {
            st.executeUpdate("DELETE FROM events");
            st.executeUpdate("DELETE FROM heatmaps");
            st.executeUpdate("DELETE FROM sharded_events");
            st.executeUpdate("DELETE FROM sharded_heatmaps");
        } catch (SQLException ex) {
            System.out.println(ex);
        }
    }

    public File exportEventsCsv() throws Exception {
        // Adjust the event names to your exact values
        List<String> eventNames = List.of("$$heatmap", "$right_click", "$table_scroll");

        File tmp = Files.createTempFile("events-", ".csv").toFile();

        // Build an IN (?, ?, ?) clause dynamically
        String placeholders = String.join(", ", Collections.nCopies(eventNames.size(), "?"));
        LocalDateTime yesterday = LocalDateTime.now();
        yesterday.minusDays(1);
        String sql = "SELECT * FROM events WHERE event IN (" + placeholders + ") AND timestamp >= '" + yesterday + "' ORDER BY event ASC";

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(tmp));
             CSVPrinter csv = new CSVPrinter(writer, CSVFormat.DEFAULT);
             PreparedStatement ps = con.prepareStatement(sql, ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY)) {

            // For some drivers you can hint streaming with fetch size (ClickHouse may ignore/honor differently)
            // ps.setFetchSize(1000);

            for (int i = 0; i < eventNames.size(); i++) {
                ps.setString(i + 1, eventNames.get(i));
            }

            try (ResultSet rs = ps.executeQuery()) {
                writeResultSetToCsv(rs, csv);
            }
            csv.flush();
        }

        return tmp;
    }

    public File exportHeatmapsCsv() throws Exception {
        File tmp = Files.createTempFile("heatmaps-", ".csv").toFile();
        LocalDateTime yesterday = LocalDateTime.now();
        yesterday.minusDays(1);

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(tmp));
             CSVPrinter csv = new CSVPrinter(writer, CSVFormat.DEFAULT);
             ResultSet rs = st.executeQuery("SELECT * FROM heatmaps WHERE timestamp >= '" + yesterday + "'");) {

            writeResultSetToCsv(rs, csv);
            csv.flush();
        }

        return tmp;
    }

    private static void writeResultSetToCsv(ResultSet rs, CSVPrinter csv) throws Exception {
        ResultSetMetaData md = rs.getMetaData();
        int cols = md.getColumnCount();
        boolean headerWritten = false;

        while (rs.next()) {
            if (!headerWritten) {
                for (int i = 1; i <= cols; i++) {
                    csv.print(md.getColumnLabel(i));
                }
                csv.println();
                headerWritten = true;
            }
            for (int i = 1; i <= cols; i++) {
                csv.print(rs.getObject(i));
            }
            csv.println();
        }
    }
    public List<ApiHeatmapGetDTO> getRightClickHeatmap(String type, String date, String urlExact, String aggregation) {
        Map<KeyMap, Integer> heatmapResult = new HashMap<>();
        List<ApiHeatmapGetDTO> results = new ArrayList<>();
        if (type.equals("gridscroll")) {
            type = "$table_scroll";
        } else if (type.equals("rightclick")) {
            type = "$right_click";
        }
        try {
            urlExact = getUrlExact(urlExact);
            date = getTheDate(date).toString();
            StringBuilder sql = new StringBuilder(
                    "SELECT * FROM events WHERE event = '" + type + "'");

            sql.append(" And timestamp >= '" + date + "'");

            if (aggregation.equals("unique_visitors")) {
                String unique_visitor;
                StringBuilder sqlVisitor = new StringBuilder(
                        "SELECT id FROM person ORDER BY rand() LIMIT 1");
                ResultSet rs = st.executeQuery(sqlVisitor.toString());
                rs.next();
                unique_visitor = rs.getString("id");

                sql.append(" And person_id = '" + unique_visitor + "'");
            }

            ResultSet rs = st.executeQuery(sql.toString());
            int count = 0;
            while (rs.next()) {
                float viewPortWidth = 1;
                int x = 0;
                int y = 0;
                String properties = rs.getString("properties");
                properties = properties.substring(1, properties.length() - 1);
                List<String> listProp = splitOnCommaOutsideBraces(properties, ',');
                boolean flag = false;
                for (String property : listProp) {
                    List<String> values = splitUrlAndProps(property);
                    if (values.getFirst().charAt(0) == '"') {
                        values.set(0, values.getFirst().substring(1, values.getFirst().length() - 1));
                    }
                    if (values.get(1).charAt(0) == '"') {
                        values.set(1, values.get(1).substring(1, values.get(1).length() - 1));
                    }
                    if (values.getFirst().isBlank())
                        continue;
                    if (values.getFirst().equals("$viewport_width")) {
                        viewPortWidth = Integer.parseInt(values.get(1));
                    } else if (values.getFirst().equals("x")) {
                        x = (int)Float.parseFloat(values.get(1));
                    } else if (values.getFirst().equals("y")) {
                        y = (int)Float.parseFloat(values.get(1));
                    } else if(values.getFirst().equals("$current_url") && !urlExact.equals(values.get(1))) {
                        flag = true;
                        break;
                    }
                }
                if(flag) continue;
                KeyMap keyMap = new KeyMap();
                keyMap.y = toNearestFive(y);
                keyMap.x = toNearestFive(x) / viewPortWidth;
                DecimalFormat df = new DecimalFormat("#.00");
                keyMap.x = (Float.parseFloat(df.format(keyMap.x)));
                keyMap.fixed = (false);
                if (!heatmapResult.containsKey(keyMap)) {
                    heatmapResult.put(keyMap, 1);
                } else {
                    heatmapResult.replace(keyMap, heatmapResult.get(keyMap) + 1);
                }
            }
        } catch (Exception ex) {
            System.out.println(ex);
        }
        for (Map.Entry<KeyMap, Integer> entry : heatmapResult.entrySet()) {
            ApiHeatmapGetDTO heatmapDTO = new ApiHeatmapGetDTO();
            heatmapDTO.setKeyMap(entry.getKey(), entry.getValue());
            results.add(heatmapDTO);
        }
        for (ApiHeatmapGetDTO heatmapDTO : results) {
            System.out.println(heatmapDTO.getPointer_y() + " " + heatmapDTO.getPointer_relative_x());
        }
        System.out.println("results: " + results.size());
        return results;
    }

    public List<ApiHeatmapGetDTO> getAllHeatmap(String type, String date, String urlExact, String aggregation) {
        Map<KeyMap, Integer> heatmapResult = new HashMap<>();
        List<ApiHeatmapGetDTO> results = new ArrayList<>();
        try {
            urlExact = getUrlExact(urlExact);
            date = getTheDate(date).toString();
            StringBuilder sql = new StringBuilder(
                    "SELECT * FROM events WHERE event = '$$heatmap'");

            sql.append(" And timestamp >= '" + date + "'");

            if (aggregation.equals("unique_visitors")) {
                String unique_visitor;
                StringBuilder sqlVisitor = new StringBuilder(
                        "SELECT id FROM person ORDER BY rand() LIMIT 1");
                ResultSet rs = st.executeQuery(sqlVisitor.toString());
                rs.next();
                unique_visitor = rs.getString("id");

                sql.append(" And person_id = '" + unique_visitor + "'");
            }

            ResultSet rs = st.executeQuery(sql.toString());
            while (rs.next()) {
                float viewPortWidth = 1;
                String properties = rs.getString("properties");
                properties = properties.substring(1, properties.length() - 1);
                List<String> listProp = splitOnCommaOutsideBraces(properties, ',');
                for (String property : listProp) {
                    List<String> values = splitOnCommaOutsideBraces(property, ':');
                    if (values.getFirst().charAt(0) == '"') {
                        values.set(0, values.getFirst().substring(1, values.getFirst().length() - 1));
                    }
                    if (values.getFirst().isBlank())
                        continue;
                    if (values.getFirst().equals("$viewport_width")) {
                        viewPortWidth = Integer.parseInt(values.get(1));
                    }
                }
                for (String property : listProp) {
                    List<String> values = splitOnCommaOutsideBraces(property, ':');
                    if (values.getFirst().charAt(0) == '"') {
                        values.set(0, values.getFirst().substring(1, values.getFirst().length() - 1));
                    }
                    if (values.getFirst().isBlank())
                        continue;
                    if (values.getFirst().equals("$heatmap_data")) {
                        if (values.get(1).isBlank())
                            continue;
                        if (values.get(1).charAt(0) == '{') {
                            values.set(1, values.get(1).substring(1, values.get(1).length() - 1));
                        }
                        List<String> dataValues = splitUrlAndProps(values.get(1));
                        dataValues.set(0, dataValues.get(0).substring(1, dataValues.get(0).length() - 1));
                        if (dataValues.get(0).isBlank() || !urlExact.equals(dataValues.get(0)))
                            continue;
                        if (dataValues.get(1).isBlank())
                            continue;
                        dataValues.set(1, dataValues.get(1).substring(1, dataValues.get(1).length() - 1));
                        List<String> eachMouseValues = splitOnCommaOutsideBraces(dataValues.get(1), ',');
                        for (String value : eachMouseValues) {
                            value = value.substring(1, value.length() - 1);
                            String[] mouseValues = value.split(",");
                            if (!mouseValues[1].split(":")[1].equals('"' + type + '"')) {
                                continue;
                            }
                            KeyMap keyMap = new KeyMap();
                            keyMap.y = (toNearestFive(Integer.parseInt(mouseValues[3].split(":")[1])));
                            keyMap.x = (toNearestFive(Integer.parseInt(mouseValues[2].split(":")[1]))) / viewPortWidth;
                            DecimalFormat df = new DecimalFormat("#.00");
                            keyMap.x = (Float.parseFloat(df.format(keyMap.x)));
                            keyMap.fixed = (false);
                            if (!heatmapResult.containsKey(keyMap)) {
                                heatmapResult.put(keyMap, 1);
                            } else {
                                heatmapResult.replace(keyMap, heatmapResult.get(keyMap) + 1);
                            }
                        }
                    }

                }
            }
        } catch (Exception ex) {
            System.out.println(ex);
        }
        for (Map.Entry<KeyMap, Integer> entry : heatmapResult.entrySet()) {
            ApiHeatmapGetDTO heatmapDTO = new ApiHeatmapGetDTO();
            heatmapDTO.setKeyMap(entry.getKey(), entry.getValue());
            results.add(heatmapDTO);
        }
        return results;
    }

    private LocalDateTime getTheDate(String val) {
        char suf = val.charAt(val.length() - 1);
        int day;
        if (suf != 't') {
            day = Integer.parseInt(val.substring(1, val.length() - 1));
        } else {
            day = 1;
        }
        switch (suf) {
            case 'h':
                day = 1;
                break;
            case 'w':
                day *= 7;
                break;
            case 'm':
                day *= 30;
                break;
            case 'y':
                day *= 365;
                break;
        }
        return LocalDateTime.now().minusDays(day);
    }

    private String getUrlExact(String val) {
        String temp;
        temp = val.replace("%3A", ":");
        return temp.replace("%2F", "/");
    }

    private static List<String> splitOnCommaOutsideBraces(String s, char div) {
        List<String> parts = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        int depth = 0;

        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '{' || c == '[' || c == '(') {
                depth++;
                cur.append(c);
            } else if (c == '}' || c == ']' || c == ')') {
                depth = Math.max(0, depth - 1);
                cur.append(c);
            } else if (c == div && depth == 0) {
                parts.add(cur.toString().trim());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        if (!cur.isEmpty())
            parts.add(cur.toString().trim());
        return parts;
    }

    private static List<String> splitUrlAndProps(String s) {
        List<String> parts = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        int depth = 0;
        int cnt = 0;

        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"') {
                cnt++;
                cur.append(c);
            } else if (c == '[') {
                depth++;
                cur.append(c);
            } else if (c == ']') {
                depth = Math.max(0, depth - 1);
                cur.append(c);
            } else if (c == ':' && depth == 0 && cnt % 2 == 0) {
                parts.add(cur.toString().trim());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        if (!cur.isEmpty())
            parts.add(cur.toString().trim());
        return parts;
    }

    private static int toNearestFive(int val) {
        int mod = val % 5;
        if (mod < 3) {
            return val - mod;
        } else {
            return val + (5 - mod);
        }
    }
}
